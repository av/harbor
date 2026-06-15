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
import research.workflow as workflow_mod

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
  timeout) to list files actually changed in the working tree. Models can also
  call the `git_diff_workspace` tool for the same summary during exploration.
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
- `allow_collateral` — when true, extra files outside hinted scope warn only unless
  the user said `only X`. When false, any out-of-scope file triggers revision.
  Default: `true`

```bash
harbor boost modules add diffscope
harbor config set HARBOR_BOOST_DIFFSCOPE_ENABLED true
harbor config set HARBOR_BOOST_WORKSPACE_ROOT /workspace/myproject
```

**Workflow presets**

- `scope-guard` (`tools`, `diffscope`, `autocheck`, `final`) — lightweight scope enforcement for focused bugfixes
- `agent-code` (`tools`, `sightline`, `diffscope`, `autocheck`, `final`) — sandbox scope enforcement
- Custom example: `scope-check=tools,keel,autocheck,diffscope,final` via `HARBOR_BOOST_WORKFLOWS`

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
  "write_workspace_file",
})

GIT_DIFF_TIMEOUT = 5.0

REVISE_PROMPT = """
<instruction>
Revise the answer to stay within the user's stated file scope.
This is your only revision — produce the final scoped answer in one pass.

Rules:
- Make a minimal diff: touch ONLY files listed under allowed_paths.
- Do NOT modify, cite, or add hunks for any forbidden_paths or out_of_scope_paths.
- Remove every change for out-of-scope paths; do not relocate those edits elsewhere.
- When git_evidence is present, treat listed paths as actually changed in the workspace.
- Do not mention diffscope. Return only the revised answer for the user.
</instruction>

<allowed_paths>
{allowed_paths}
</allowed_paths>

<forbidden_paths>
{forbidden_paths}
</forbidden_paths>

<out_of_scope_paths>
{out_of_scope_paths}
</out_of_scope_paths>

<git_evidence>
{git_evidence}
</git_evidence>

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

_NO_PATHS_LINE = "- (none)"


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


def diffscope_gate_reason(chat: "ch.Chat") -> str:
  """Return ``triggered`` when scope checks should run, else a pass-through reason."""
  if not config.DIFFSCOPE_ENABLED.value:
    return "disabled"
  if not deliverable.is_coding_deliverable(chat):
    return "not_deliverable"
  scope = extract_user_scope(chat)
  if not scope.has_constraints:
    return "no_scope_constraints"
  return "triggered"


def needs_diffscope(chat: "ch.Chat") -> bool:
  return diffscope_gate_reason(chat) == "triggered"


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
  paths: list[str] | None = None,
) -> tuple[list[str], str] | None:
  """Run git diff and return changed paths plus stat summary, or None on failure."""
  cwd = str(root)
  name_cmd = ["git", "diff", "--name-only"]
  stat_cmd = ["git", "diff", "--stat"]
  if paths:
    name_cmd.extend(["--", *paths])
    stat_cmd.extend(["--", *paths])
  try:
    name_proc = subprocess.run(
      name_cmd,
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
      stat_cmd,
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
  """Prefer workspace git diff; merge draft paths so scope checks stay grounded."""
  heuristic_paths = extract_response_paths(text, chat)
  root = config.WORKSPACE_ROOT.value
  if root and is_git_workspace(root):
    result = run_git_diff(root)
    if result is not None:
      paths, stat = result
      merged = _collect_unique([*paths, *heuristic_paths])
      logger.debug(
        f"{ID_PREFIX}: git mode — {len(paths)} git path(s), "
        f"{len(heuristic_paths)} draft path(s), {len(merged)} merged"
      )
      return ChangedPathsSnapshot(paths=merged, stat=stat, mode="git")

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


def partition_violations(
  violations: list[ScopeViolation],
  scope: UserScope,
  *,
  allow_collateral: bool | None = None,
) -> tuple[list[ScopeViolation], list[ScopeViolation]]:
  """Split violations into blockers and collateral warnings.

  Forbidden paths and explicit `only X` scope always block. Out-of-scope paths
  against hinted scope become collateral warnings when collateral is allowed.
  """
  if allow_collateral is None:
    allow_collateral = config.DIFFSCOPE_ALLOW_COLLATERAL.value

  strict_only = bool(scope.allowed)
  blocking: list[ScopeViolation] = []
  collateral: list[ScopeViolation] = []

  for violation in violations:
    if violation.reason == "forbidden":
      blocking.append(violation)
      continue

    if violation.reason == "out_of_scope" and not strict_only and allow_collateral:
      collateral.append(violation)
      continue

    blocking.append(violation)

  return blocking, collateral


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

  if scope.forbidden:
    lines.append("<forbidden_paths>")
    lines.extend(f"- {path}" for path in scope.forbidden)
    lines.append("</forbidden_paths>")

  lines.append("</file_scope_violations>")
  return "\n".join(lines)


def build_revise_scope_sections(
  scope: UserScope,
  violations: list[ScopeViolation],
  snapshot: ChangedPathsSnapshot | None = None,
) -> dict[str, str]:
  """Format explicit allowed/forbidden/out-of-scope lists for the revise prompt."""
  if scope.allowed:
    allowed_lines = [f"- {path}" for path in scope.allowed]
  elif scope.hinted:
    allowed_lines = [f"- {path}" for path in scope.hinted]
  else:
    allowed_lines = [
      "- (none explicitly stated — keep only in-scope edits from the draft)",
    ]

  forbidden_lines = [f"- {path}" for path in scope.forbidden] or [_NO_PATHS_LINE]

  git_paths = {path.lower() for path in (snapshot.paths if snapshot else [])}
  out_of_scope_lines: list[str] = []
  for violation in violations:
    if violation.reason != "out_of_scope":
      continue
    line = f"- {violation.path}"
    if snapshot is not None and snapshot.mode == "git":
      if violation.path.lower() in git_paths:
        line += " (confirmed changed in workspace git diff)"
      else:
        line += " (cited in draft; not in workspace git diff)"
    out_of_scope_lines.append(line)
  if not out_of_scope_lines:
    out_of_scope_lines = [_NO_PATHS_LINE]

  if snapshot is not None and snapshot.mode == "git":
    git_lines = ["Workspace git diff — files changed in the working tree:"]
    git_lines.extend(f"- {path}" for path in snapshot.paths)
    if snapshot.stat:
      git_lines.extend(["", "<git_diff_stat>", snapshot.stat, "</git_diff_stat>"])
    git_evidence = "\n".join(git_lines)
  else:
    git_evidence = "(git diff unavailable — rely on scope_correction and draft paths)"

  return {
    "allowed_paths": "\n".join(allowed_lines),
    "forbidden_paths": "\n".join(forbidden_lines),
    "out_of_scope_paths": "\n".join(out_of_scope_lines),
    "git_evidence": git_evidence,
  }


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
  *,
  scope: UserScope | None = None,
  violations: list[ScopeViolation] | None = None,
  snapshot: ChangedPathsSnapshot | None = None,
) -> str:
  scope_sections = (
    build_revise_scope_sections(scope, violations or [], snapshot)
    if scope is not None
    else {
      "allowed_paths": _NO_PATHS_LINE,
      "forbidden_paths": _NO_PATHS_LINE,
      "out_of_scope_paths": _NO_PATHS_LINE,
      "git_evidence": "(scope details unavailable — rely on scope_correction)",
    }
  )
  intermediate = _cheap_llm(llm)
  revised = await intermediate.chat_completion(
    prompt=REVISE_PROMPT,
    conversation=str(chat),
    draft=draft,
    correction=correction,
    resolve=True,
    params={"temperature": 0.2},
    **scope_sections,
  )
  return (revised or draft).strip()


async def emit_final(llm: "llm.LLM", final_text: str) -> None:
  if final_text:
    await llm.emit_message(final_text)


async def apply(chat: "ch.Chat", llm: "llm.LLM", config: dict | None = None):
  module_cfg = config or {}
  gate_reason = diffscope_gate_reason(chat)
  if gate_reason != "triggered":
    logger.debug(f"{ID_PREFIX}: Pass-through — {gate_reason}")
    return await workflow_mod.complete_or_defer(llm, module_cfg)

  scope = extract_user_scope(chat)

  await llm.emit_status("Diffscope: drafting...")
  try:
    draft = await llm.stream_chat_completion(emit=False)
  except Exception as exc:
    logger.error(f"{ID_PREFIX}: draft failed: {exc}")
    return await workflow_mod.complete_or_defer(llm, module_cfg)

  draft = (draft or "").strip()
  if not draft:
    logger.warning(f"{ID_PREFIX}: empty draft, passing through")
    return await workflow_mod.complete_or_defer(llm, module_cfg)

  snapshot = collect_changed_paths(draft, chat)
  changed_paths = snapshot.paths
  violations = find_violations(changed_paths, scope)
  blocking_violations, collateral_violations = partition_violations(violations, scope)
  missing_paths = await verify_workspace_paths(changed_paths)

  if collateral_violations:
    collateral_paths = ", ".join(violation.path for violation in collateral_violations)
    logger.warning(
      f"{ID_PREFIX}: collateral files outside hinted scope — {collateral_paths}"
    )

  if not blocking_violations and not missing_paths:
    mode_label = "git" if snapshot.mode == "git" else "heuristic"
    status = f"Diffscope: scope OK ({mode_label})"
    if collateral_violations:
      collateral_paths = ", ".join(violation.path for violation in collateral_violations)
      status = f"{status} — collateral: {collateral_paths}"
    await llm.emit_status(status)
    await emit_final(llm, draft)
    return draft

  correction = build_correction_note(
    blocking_violations,
    missing_paths,
    scope,
    snapshot,
  )
  logger.warning(
    f"{ID_PREFIX}: scope issues — {len(blocking_violations)} blocking violation(s), "
    f"{len(collateral_violations)} collateral warning(s), "
    f"{len(missing_paths)} missing path(s)"
  )
  chat.system(
    "Diffscope flagged file paths outside the user's stated scope. "
    "Revise to stay within allowed paths."
  )

  await llm.emit_status("Diffscope: revising for scope...")
  try:
    final_text = await revise_with_correction(
      chat,
      llm,
      draft,
      correction,
      scope=scope,
      violations=blocking_violations,
      snapshot=snapshot,
    )
  except Exception as exc:
    logger.error(f"{ID_PREFIX}: revision failed: {exc}")
    final_text = draft

  await emit_final(llm, final_text)
  return final_text