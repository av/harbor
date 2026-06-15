"""Post-deliverable scope guard for Harbor Boost."""

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import chat as ch
import config
import deliverable
import log

if TYPE_CHECKING:
  import llm

ID_PREFIX = "diffscope"

DOCS = """
`diffscope` is a post-deliverable scope guard for coding turns. On deliverable
requests it drafts the model answer and compares changed file paths to scope the
user stated in recent messages (`only X`, `don't touch Y`, quoted paths).

**Path grounding modes**

- **Git mode** (preferred): when `HARBOR_BOOST_WORKSPACE_ROOT` points at a git
  repo, `diffscope` runs `git diff --name-only` and `git diff --stat` (5s
  timeout) to list files actually changed in the working tree.
- **Heuristic mode** (fallback): when git is unavailable, paths are extracted
  from the draft (code fences, diff headers, backticks) and file-tool arguments
  in chat history.

When `HARBOR_BOOST_WORKSPACE_ROOT` is set, cited workspace paths are also
verified with `read_workspace_file`. Out-of-scope or missing paths trigger a
correction note and **one** revision hop before the answer is emitted.

**When to use**

- Coding deliverables where the user states file scope (`only X`, `don't touch Y`)
- Post-deliverable guard: compares changed paths against recent constraints
- Optional hardening atop `keel` anchoring or `sightline` scratch guards

**Limitation:** User scope is inferred from recent message heuristics. Scratch
file tools (`read_file`, `write_file`) are not tracked — only workspace reads
verify repo paths. Git mode reflects unstaged `git diff` output only.

**Parameters**

- `enabled` — when false, pass through without scope checks. Default: `true`
- `max_user_turns` — recent user messages scanned for scope hints. Default: `5`
- `max_workspace_files` — workspace existence checks per request. Default: `5`

```bash
harbor boost modules add diffscope
harbor config set HARBOR_BOOST_DIFFSCOPE_ENABLED true
harbor config set HARBOR_BOOST_WORKSPACE_ROOT /workspace/myproject
```

**Workflow presets**

- Not included in built-in presets; append after `autocheck` in a custom workflow
- Example: `scope-check=tools,keel,autocheck,diffscope,final` via `HARBOR_BOOST_WORKFLOWS`

**Standalone**

```bash
docker run \\
  -e "HARBOR_BOOST_OPENAI_URLS=http://172.17.0.1:11434/v1" \\
  -e "HARBOR_BOOST_OPENAI_KEYS=sk-ollama" \\
  -e "HARBOR_BOOST_MODULES=diffscope" \\
  -e "HARBOR_BOOST_WORKSPACE_ROOT=/workspace" \\
  -p 8004:8000 \\
  ghcr.io/av/harbor-boost:latest
```
"""

logger = log.setup_logger(ID_PREFIX)

DIFF_HEADER_RE = re.compile(r"^(?:---|\+\+\+)\s+[ab]/(?P<path>.+)$", re.MULTILINE)
DIFF_GIT_RE = re.compile(r"^diff --git a/(?P<a>.+?) b/(?P<b>.+?)$", re.MULTILINE)
FENCE_PATH_RE = re.compile(
  r"```(?:\d+:\d+:|[\w+.-]*:)(?P<path>(?:[\w.-]+/)+[\w.-]+)",
  re.IGNORECASE,
)
ONLY_RE = re.compile(
  r"\b(?:only|just|limit(?:ed)?\s+to|stick\s+to|focus\s+on|change\s+only)\s+"
  r"(?:(?:change|edit|modify|update|fix|touch)\s+)?(?:the\s+)?[`'\"]?"
  r"((?:[\w.-]+/)*[\w.-]+\.[\w]+)",
  re.IGNORECASE,
)
DONT_TOUCH_RE = re.compile(
  r"\b(?:don't\s+touch|do\s+not\s+(?:touch|modify|change|edit)|never\s+touch|leave\s+alone)\s+"
  r"(?:the\s+)?[`'\"]?"
  r"((?:[\w.-]+/)*[\w.-]+\.[\w]+)",
  re.IGNORECASE,
)
FILE_TOOL_NAMES = frozenset({
  "write_file",
  "read_file",
  "delete_file",
  "read_workspace_file",
})

GIT_DIFF_TIMEOUT = 5.0

REVISE_PROMPT = """
<instruction>
Revise the answer to stay within the user's stated file scope.
Remove or relocate changes to out-of-scope paths. Do not mention diffscope.
Return only the revised answer for the user.
</instruction>

<conversation>
{conversation}
</conversation>

<draft>
{draft}
</draft>

<scope_correction>
{correction}
</scope_correction>
""".strip()


@dataclass
class UserScope:
  allowed: list[str] = field(default_factory=list)
  hinted: list[str] = field(default_factory=list)
  forbidden: list[str] = field(default_factory=list)

  @property
  def has_constraints(self) -> bool:
    return bool(self.allowed or self.hinted or self.forbidden)


@dataclass
class ScopeViolation:
  path: str
  reason: str


@dataclass
class ChangedPathsSnapshot:
  paths: list[str] = field(default_factory=list)
  stat: str = ""
  mode: Literal["git", "heuristic"] = "heuristic"


def needs_diffscope(chat: "ch.Chat") -> bool:
  if not config.DIFFSCOPE_ENABLED.value:
    return False
  return deliverable.is_coding_deliverable(chat)


def _collect_unique(paths: list[str]) -> list[str]:
  unique: list[str] = []
  seen: set[str] = set()
  for path in paths:
    norm = path.lower()
    if path and norm not in seen:
      seen.add(norm)
      unique.append(path)
  return unique


def recent_user_texts(chat: "ch.Chat", max_turns: int | None = None) -> list[str]:
  limit = max_turns if max_turns is not None else config.DIFFSCOPE_MAX_USER_TURNS.value
  users = chat.match(role="user")
  return [(node.content or "").strip() for node in users[-max(1, limit):]]


def extract_user_scope(chat: "ch.Chat") -> UserScope:
  allowed: list[str] = []
  hinted: list[str] = []
  forbidden: list[str] = []

  for text in recent_user_texts(chat):
    if not text:
      continue

    for match in ONLY_RE.finditer(text):
      allowed.append(deliverable.normalize_repo_path(match.group(1)))

    for match in DONT_TOUCH_RE.finditer(text):
      forbidden.append(deliverable.normalize_repo_path(match.group(1)))

    for match in deliverable.FILE_PATH_RE.finditer(text):
      hinted.append(deliverable.normalize_repo_path(match.group(0)))

    for match in deliverable.BACKTICK_PATH_RE.finditer(text):
      hinted.append(deliverable.normalize_repo_path(match.group(1)))

  return UserScope(
    allowed=_collect_unique(allowed),
    hinted=_collect_unique(hinted),
    forbidden=_collect_unique(forbidden),
  )


def _add_path(paths: list[str], seen: set[str], raw: str) -> None:
  path = deliverable.normalize_repo_path(raw)
  if not path:
    return
  key = path.lower()
  if key not in seen:
    seen.add(key)
    paths.append(path)


def extract_response_paths(text: str, chat: "ch.Chat | None" = None) -> list[str]:
  paths: list[str] = []
  seen: set[str] = set()

  for source in (text,):
    if not source:
      continue
    for match in deliverable.FILE_PATH_RE.finditer(source):
      _add_path(paths, seen, match.group(0))
    for match in deliverable.BACKTICK_PATH_RE.finditer(source):
      _add_path(paths, seen, match.group(1))
    for match in DIFF_HEADER_RE.finditer(source):
      _add_path(paths, seen, match.group("path"))
    for match in DIFF_GIT_RE.finditer(source):
      _add_path(paths, seen, match.group("a"))
      _add_path(paths, seen, match.group("b"))
    for match in FENCE_PATH_RE.finditer(source):
      _add_path(paths, seen, match.group("path"))

  if chat is not None:
    for node in chat.match(role="assistant"):
      for tool_call in node.tool_calls or []:
        function = tool_call.get("function") or {}
        if function.get("name") not in FILE_TOOL_NAMES:
          continue
        args_raw = function.get("arguments") or "{}"
        try:
          args = json.loads(args_raw) if args_raw.strip() else {}
        except json.JSONDecodeError:
          continue
        path = args.get("file_path") or args.get("path")
        if path:
          _add_path(paths, seen, path)

  return paths


def is_git_workspace(root: str | Path | None = None) -> bool:
  """Return True when the workspace root is inside a git repository."""
  resolved = Path(root or config.WORKSPACE_ROOT.value or "")
  if not resolved.is_dir():
    return False
  git_path = resolved / ".git"
  return git_path.is_dir() or git_path.is_file()


def run_git_diff(
  root: str | Path,
  *,
  timeout: float = GIT_DIFF_TIMEOUT,
) -> tuple[list[str], str] | None:
  """Run git diff and return changed paths plus stat summary, or None on failure."""
  cwd = str(root)
  try:
    name_proc = subprocess.run(
      ["git", "diff", "--name-only"],
      cwd=cwd,
      capture_output=True,
      text=True,
      timeout=timeout,
      check=False,
    )
    if name_proc.returncode != 0:
      logger.debug(
        f"{ID_PREFIX}: git diff --name-only failed (rc={name_proc.returncode}): "
        f"{(name_proc.stderr or '').strip()}"
      )
      return None

    stat_proc = subprocess.run(
      ["git", "diff", "--stat"],
      cwd=cwd,
      capture_output=True,
      text=True,
      timeout=timeout,
      check=False,
    )
    stat = (stat_proc.stdout or "").strip()
    if stat_proc.returncode != 0:
      logger.debug(
        f"{ID_PREFIX}: git diff --stat failed (rc={stat_proc.returncode}): "
        f"{(stat_proc.stderr or '').strip()}"
      )
      stat = ""

    paths: list[str] = []
    seen: set[str] = set()
    for line in (name_proc.stdout or "").splitlines():
      raw = line.strip()
      if raw:
        _add_path(paths, seen, raw)

    return paths, stat
  except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
    logger.debug(f"{ID_PREFIX}: git diff unavailable: {exc}")
    return None


def collect_changed_paths(text: str, chat: "ch.Chat | None" = None) -> ChangedPathsSnapshot:
  """Prefer workspace git diff; fall back to response path heuristics."""
  root = config.WORKSPACE_ROOT.value
  if root and is_git_workspace(root):
    result = run_git_diff(root)
    if result is not None:
      paths, stat = result
      logger.debug(
        f"{ID_PREFIX}: git mode — {len(paths)} changed path(s)"
      )
      return ChangedPathsSnapshot(paths=paths, stat=stat, mode="git")

  heuristic_paths = extract_response_paths(text, chat)
  logger.debug(
    f"{ID_PREFIX}: heuristic mode — {len(heuristic_paths)} path(s) from response"
  )
  return ChangedPathsSnapshot(paths=heuristic_paths, stat="", mode="heuristic")


def path_matches_scope(path: str, candidates: list[str]) -> bool:
  norm = path.lower().strip()
  for candidate in candidates:
    cand = candidate.lower().strip()
    if norm == cand:
      return True
    if norm.endswith("/" + cand) or cand.endswith("/" + norm):
      return True
    if norm.startswith(cand.rstrip("/") + "/"):
      return True
  return False


def find_violations(paths: list[str], scope: UserScope) -> list[ScopeViolation]:
  violations: list[ScopeViolation] = []
  seen: set[str] = set()

  for path in paths:
    key = path.lower()
    if key in seen:
      continue
    seen.add(key)

    if scope.forbidden and path_matches_scope(path, scope.forbidden):
      violations.append(ScopeViolation(path=path, reason="forbidden"))
      continue

    if scope.allowed and not path_matches_scope(path, scope.allowed):
      violations.append(ScopeViolation(path=path, reason="out_of_scope"))
    elif scope.hinted and not scope.allowed and not path_matches_scope(path, scope.hinted):
      violations.append(ScopeViolation(path=path, reason="out_of_scope"))

  return violations


async def verify_workspace_paths(paths: list[str]) -> list[str]:
  if not config.WORKSPACE_ROOT.value:
    return []

  from modules.tools import read_workspace_file

  missing: list[str] = []
  limit = max(0, config.DIFFSCOPE_MAX_WORKSPACE_FILES.value)

  for path in paths[:limit]:
    try:
      await read_workspace_file(path)
    except FileNotFoundError:
      missing.append(path)
    except Exception as exc:
      logger.debug(f"{ID_PREFIX}: skip workspace check for '{path}': {exc}")

  return missing


def build_correction_note(
  violations: list[ScopeViolation],
  missing_paths: list[str],
  scope: UserScope,
  snapshot: ChangedPathsSnapshot | None = None,
) -> str:
  lines = ["<file_scope_violations>"]

  if snapshot is not None:
    if snapshot.mode == "git":
      lines.append("Grounding: workspace git diff (actual changed files)")
    else:
      lines.append("Grounding: response path heuristics (git unavailable)")
    if snapshot.stat:
      lines.append("<git_diff_stat>")
      lines.append(snapshot.stat)
      lines.append("</git_diff_stat>")

  for violation in violations:
    if violation.reason == "forbidden":
      lines.append(f"- FORBIDDEN: {violation.path} (user asked not to touch this path)")
    else:
      lines.append(f"- OUT_OF_SCOPE: {violation.path}")

  for path in missing_paths:
    lines.append(f"- MISSING: {path} (not found under workspace root)")

  if scope.allowed:
    lines.append("<allowed_paths>")
    lines.extend(f"- {path}" for path in scope.allowed)
    lines.append("</allowed_paths>")
  elif scope.hinted:
    lines.append("<hinted_paths>")
    lines.extend(f"- {path}" for path in scope.hinted)
    lines.append("</hinted_paths>")

  lines.append("</file_scope_violations>")
  return "\n".join(lines)


def _cheap_llm(llm: "llm.LLM") -> "llm.LLM":
  import llm as llm_mod

  return llm_mod.LLM(
    url=llm.url,
    headers=llm.headers,
    query_params=llm.query_params,
    model=llm.model,
    params={},
    messages=[{"role": "user", "content": ""}],
    module=None,
  )


async def revise_with_correction(
  chat: "ch.Chat",
  llm: "llm.LLM",
  draft: str,
  correction: str,
) -> str:
  intermediate = _cheap_llm(llm)
  revised = await intermediate.chat_completion(
    prompt=REVISE_PROMPT,
    conversation=str(chat),
    draft=draft,
    correction=correction,
    resolve=True,
    params={"temperature": 0.2},
  )
  return (revised or draft).strip()


async def emit_final(llm: "llm.LLM", final_text: str) -> None:
  if final_text:
    await llm.emit_message(final_text)


async def apply(chat: "ch.Chat", llm: "llm.LLM"):
  if not needs_diffscope(chat):
    logger.debug(f"{ID_PREFIX}: pass-through — not a coding deliverable")
    return await llm.stream_final_completion()

  scope = extract_user_scope(chat)
  if not scope.has_constraints:
    logger.debug(f"{ID_PREFIX}: pass-through — no user scope constraints")
    return await llm.stream_final_completion()

  await llm.emit_status("Diffscope: drafting...")
  try:
    draft = await llm.stream_final_completion(emit=False)
  except Exception as exc:
    logger.error(f"{ID_PREFIX}: draft failed: {exc}")
    return await llm.stream_final_completion()

  draft = (draft or "").strip()
  if not draft:
    logger.warning(f"{ID_PREFIX}: empty draft, passing through")
    return await llm.stream_final_completion()

  snapshot = collect_changed_paths(draft, chat)
  changed_paths = snapshot.paths
  violations = find_violations(changed_paths, scope)
  missing_paths = await verify_workspace_paths(changed_paths)

  if not violations and not missing_paths:
    mode_label = "git" if snapshot.mode == "git" else "heuristic"
    await llm.emit_status(f"Diffscope: scope OK ({mode_label})")
    await emit_final(llm, draft)
    return draft

  correction = build_correction_note(violations, missing_paths, scope, snapshot)
  logger.warning(
    f"{ID_PREFIX}: scope issues — {len(violations)} violation(s), "
    f"{len(missing_paths)} missing path(s)"
  )
  chat.system(
    "Diffscope flagged file paths outside the user's stated scope. "
    "Revise to stay within allowed paths."
  )

  await llm.emit_status("Diffscope: revising for scope...")
  try:
    final_text = await revise_with_correction(chat, llm, draft, correction)
  except Exception as exc:
    logger.error(f"{ID_PREFIX}: revision failed: {exc}")
    final_text = draft

  await emit_final(llm, final_text)
  return final_text