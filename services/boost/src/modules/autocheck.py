"""Selective post-deliverable self-check for Harbor Boost."""

import html
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

import chat as ch
import config as boost_config
import deliverable
import log
import research.orchestrate as orchestrate
import research.workflow as workflow_mod
import tools.registry
from modules.diffscope import is_git_workspace, run_git_diff

if TYPE_CHECKING:
  import llm

ID_PREFIX = "autocheck"

DOCS = """
`autocheck` runs a lightweight self-check on coding deliverable turns before the
user sees the final answer. Non-deliverable turns (explanations, acknowledgments,
brainstorming) pass through unchanged to keep latency low.

On deliverable turns the module drafts a response, audits it with a structured
checklist (correctness, completeness, file-path grounding), optionally revises once,
then emits the final answer.

**When to use**

- Opt-in quality gate on **coding deliverable** turns — add via workflow or module list
- Enable when you want draft→audit→revise before the user sees code changes
- Safe to leave enabled in mixed chats: explanations and short acks pass through
- Set `HARBOR_BOOST_WORKSPACE_ROOT` so path citations require workspace evidence

Autocheck triggers when the latest user message carries **at least two**
deliverable signals (for example a coding keyword plus a repo-relative file path),
when the ``finish`` tool was called in recent chat history, or when the user sends
an explicit completion signal (`we're done`, `ship it`, `looks good`) after prior
coding work. Simple acknowledgments (`thanks`, `ok`, `continue`), research-only turns, and very
short messages are always skipped. In `shipyard`, pass-through turns honor
`defer_final` so the explicit `final` workflow step streams the answer.

When `HARBOR_BOOST_WORKSPACE_ROOT` is set and paths are cited, the audit cannot
return `pass` without workspace evidence — either direct `read_workspace_file`
reads, `grep_workspace` symbol checks, `list_workspace_files` directory scans, or
tool calls during workspace exploration.

Before the LLM audit, mechanical pre-checks (no model call) run when a workspace
is configured:

- **Git diff context** — in a git repo, `git diff --stat` is included in audit context
- **Path existence** — cited draft paths are verified with `read_workspace_file`
- **Code block grounding** — drafts with fenced code but zero file paths are flagged
- **Test hint** — when test files exist near changed paths, a non-blocking warning
  suggests running tests with a command inferred from `pyproject.toml` or
  `package.json` scripts when detectable

Mechanical findings are structured blockers merged into the audit before delivery.
Audit debug logs include `triggered`, `gate_reason`, `tool_calls`, and `verdict`
for troubleshooting.

**Parameters**

- `enabled` — when false, pass through without auditing. Default: `true`
- `max_passes` — maximum audit-and-revise passes. Default: `1`
- `max_workspace_files` — workspace files read per request. Default: `5`
- `workspace_file_max_chars` — characters per workspace file. Default: `50000`
- `show_audit` — when true, append a brief audit footer to the final answer and emit
  an HTML findings summary artifact for the UI. Default: `false`. Overridable per
  request via `@boost_show_audit`.

```bash
harbor boost modules add autocheck
harbor config set HARBOR_BOOST_AUTOCHECK_ENABLED true
harbor config set HARBOR_BOOST_AUTOCHECK_MAX_PASSES 1
harbor config set HARBOR_BOOST_AUTOCHECK_SHOW_AUDIT true
harbor config set HARBOR_BOOST_WORKSPACE_ROOT /workspace/myproject
```

**Workflow presets**

- `code-check` (`tools`, `autocheck`, `final`) — self-audit coding deliverables
- `scope-guard` (`tools`, `diffscope`, `autocheck`, `final`) — scoped bugfix deliverable audit
- `agent-code` (`tools`, `sightline`, `diffscope`, `autocheck`, `final`) — sandbox deliverable audit
- `shipyard` — final audit step before the downstream completion

**Standalone**

```bash
docker run \\
  -e "HARBOR_BOOST_OPENAI_URLS=http://172.17.0.1:11434/v1" \\
  -e "HARBOR_BOOST_OPENAI_KEYS=sk-ollama" \\
  -e "HARBOR_BOOST_MODULES=autocheck" \\
  -e "HARBOR_BOOST_WORKSPACE_ROOT=/workspace" \\
  -p 8004:8000 \\
  ghcr.io/av/harbor-boost:latest
```
"""

logger = log.setup_logger(ID_PREFIX)

MIN_DELIVERABLE_SIGNALS = 2
MIN_AUTOCHECK_MESSAGE_CHARS = 12

WORKSPACE_TOOL_NAMES = frozenset({
  "read_workspace_file",
  "grep_workspace",
  "list_workspace_files",
})

SYMBOL_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w+)", re.MULTILINE)
SYMBOL_CLASS_RE = re.compile(r"^\s*class\s+([A-Za-z_]\w+)", re.MULTILINE)
BACKTICK_SYMBOL_RE = re.compile(r"`([A-Za-z_]\w{2,})`")

SYMBOL_STOPWORDS = frozenset({
  "None",
  "True",
  "False",
  "self",
  "cls",
  "str",
  "int",
  "bool",
  "list",
  "dict",
  "set",
  "tuple",
  "float",
  "bytes",
})

BLOCKING_SEVERITIES = frozenset({"critical", "major"})

DRAFT_PROMPT = """
<instruction>
Draft a complete answer to the user's latest coding request.
Include concrete implementation details, file paths, and code changes where appropriate.
This draft will be audited before delivery — be precise and avoid inventing files.
</instruction>

<conversation>
{conversation}
</conversation>
""".strip()

WORKSPACE_EXPLORE_PROMPT = """
<instruction>
You are verifying a coding draft against the workspace.
Use the `read_workspace_file` tool to inspect files referenced in the draft or user request.
Use the `grep_workspace` tool to verify functions, classes, and identifiers exist in the codebase.
Use the `list_workspace_files` tool to discover files under cited directories when paths are ambiguous.
Read only paths that exist and are relevant to correctness checks.
When done exploring, reply with a short bullet list of verified facts and mismatches.
Do not rewrite the draft.
</instruction>

<referenced_paths>
{paths}
</referenced_paths>

<draft_excerpt>
{draft_excerpt}
</draft_excerpt>
""".strip()

AUDIT_PROMPT = """
<instruction>
Audit the coding draft below for delivery to the user.
Check correctness, completeness, unsafe assumptions, missing edge cases, and whether
referenced file paths match the workspace context when provided.
Return a structured verdict: "pass" when ready to ship, "revise" when material issues remain.
</instruction>

<conversation>
{conversation}
</conversation>

<workspace_context>
{workspace_context}
</workspace_context>

<workspace_exploration>
{workspace_exploration}
</workspace_exploration>

<draft>
{draft}
</draft>
""".strip()

REVISE_PROMPT = """
<instruction>
Revise the draft to fix the audit findings. Keep the same intent and scope.
Address every critical and major finding. Do not mention the audit process.
Return only the revised answer for the user.
</instruction>

<conversation>
{conversation}
</conversation>

<draft>
{draft}
</draft>

<audit_summary>
{audit_summary}
</audit_summary>

<findings>
{findings}
</findings>
""".strip()


class AuditFinding(BaseModel):
  severity: Literal["critical", "major", "minor", "info", "warn"] = Field(
    description="How blocking the issue is for shipping the answer.",
  )
  message: str = Field(description="What is wrong or risky in the draft.")
  fix_hint: str = Field(
    description="Concrete guidance for fixing the issue.",
    default="",
  )


class AuditResult(BaseModel):
  verdict: Literal["pass", "revise"] = Field(
    description="Whether the draft can ship as-is.",
  )
  summary: str = Field(
    description="One-paragraph audit summary.",
    default="",
  )
  findings: list[AuditFinding] = Field(
    description="Structured list of audit findings.",
    default_factory=list,
  )


class AuditDebug(BaseModel):
  triggered: bool = False
  gate_reason: str = ""
  tool_calls: list[dict] = Field(default_factory=list)
  verdict: Literal["pass", "revise", "skipped"] = "skipped"


def autocheck_gate_reason(chat: "ch.Chat") -> str:
  """Explain why autocheck would or would not run on this turn."""
  if not boost_config.AUTOCHECK_ENABLED.value:
    return "disabled"

  text = orchestrate.last_user_text(chat)
  if not text:
    return "empty_message"
  if deliverable.is_completion_trigger(chat):
    return "triggered"
  if deliverable.is_research_only_turn(chat):
    return "research_only"
  if deliverable.is_acknowledgment(text):
    return "acknowledgment"
  if len(text) < MIN_AUTOCHECK_MESSAGE_CHARS:
    return "short_message"
  if orchestrate.CONTINUATION_RE.search(text) and len(text) < 120:
    return "continuation"
  if not deliverable.is_coding_deliverable(chat):
    return "not_deliverable"

  signal_count = deliverable.count_deliverable_signals(chat)
  if signal_count < MIN_DELIVERABLE_SIGNALS:
    return "insufficient_signals"

  return "triggered"


def needs_autocheck(chat: "ch.Chat") -> bool:
  """Return True when this turn should run post-deliverable self-check."""
  return autocheck_gate_reason(chat) == "triggered"


def extract_workspace_paths(*texts: str) -> list[str]:
  """Collect unique repo-relative paths mentioned in draft or user text."""
  paths: list[str] = []
  seen: set[str] = set()

  for text in texts:
    if not text:
      continue

    for match in deliverable.FILE_PATH_RE.finditer(text):
      path = deliverable.normalize_repo_path(match.group(0))
      if path and path not in seen:
        seen.add(path)
        paths.append(path)

    for match in deliverable.BACKTICK_PATH_RE.finditer(text):
      path = deliverable.normalize_repo_path(match.group(1))
      if path and path not in seen:
        seen.add(path)
        paths.append(path)

  limit = max(0, boost_config.AUTOCHECK_MAX_WORKSPACE_FILES.value)
  return paths[:limit] if limit else []


def extract_audit_symbols(*texts: str, limit: int = 8) -> list[str]:
  """Collect function, class, and backtick identifiers worth verifying."""
  symbols: list[str] = []
  seen: set[str] = set()

  for text in texts:
    if not text:
      continue

    for regex in (SYMBOL_DEF_RE, SYMBOL_CLASS_RE):
      for match in regex.finditer(text):
        symbol = match.group(1)
        if symbol in seen or symbol in SYMBOL_STOPWORDS:
          continue
        seen.add(symbol)
        symbols.append(symbol)

    for match in BACKTICK_SYMBOL_RE.finditer(text):
      symbol = match.group(1)
      if symbol in seen or symbol in SYMBOL_STOPWORDS:
        continue
      seen.add(symbol)
      symbols.append(symbol)

  return symbols[: max(0, limit)]


def _workspace_tool_path(args: dict) -> str:
  return (args.get("path") or args.get("file_path") or "").strip()


def should_revise(audit: AuditResult) -> bool:
  return audit.verdict == "revise"


def successful_workspace_reads(workspace_context: str) -> list[str]:
  """Return repo-relative paths successfully read from workspace context."""
  if not workspace_context:
    return []

  reads: list[str] = []
  for match in re.finditer(r'<file path="([^"]+)"(?:\s|>)', workspace_context):
    path = match.group(1)
    error_match = re.search(
      rf'<file path="{re.escape(path)}" error="[^"]*"\s*/>',
      workspace_context,
    )
    if not error_match:
      reads.append(path)
  return reads


def extract_workspace_tool_calls(messages: list[dict]) -> list[dict]:
  """Collect workspace tool calls from a chat history slice."""
  calls: list[dict] = []
  for message in messages:
    for tool_call in message.get("tool_calls") or []:
      function = tool_call.get("function") or {}
      name = function.get("name")
      if name not in WORKSPACE_TOOL_NAMES:
        continue

      args_raw = function.get("arguments") or "{}"
      try:
        args = json.loads(args_raw) if args_raw.strip() else {}
      except json.JSONDecodeError:
        args = {"raw_arguments": args_raw}

      calls.append({
        "name": name,
        "arguments": args,
      })
  return calls


def workspace_evidence_paths(
  workspace_context: str,
  tool_calls: list[dict],
) -> list[str]:
  """Merge direct workspace reads and tool-call paths into evidence paths."""
  paths = list(successful_workspace_reads(workspace_context))
  seen = set(paths)

  for call in tool_calls:
    args = call.get("arguments") or {}
    path = _workspace_tool_path(args)
    if path and path not in seen:
      seen.add(path)
      paths.append(path)

  return paths


def workspace_evidence_satisfied(
  workspace_context: str,
  tool_calls: list[dict],
) -> bool:
  """Return True when workspace reads or grep checks were performed."""
  if successful_workspace_reads(workspace_context):
    return True

  for call in tool_calls:
    name = call.get("name")
    args = call.get("arguments") or {}
    if name == "grep_workspace" and (args.get("pattern") or "").strip():
      return True
    if name == "read_workspace_file" and _workspace_tool_path(args):
      return True
    if name == "list_workspace_files":
      return True

  return False


def requires_workspace_evidence(paths: list[str]) -> bool:
  return bool(boost_config.WORKSPACE_ROOT.value and paths)


def draft_has_code_blocks(text: str) -> bool:
  """Return True when the draft contains fenced code blocks."""
  return bool(deliverable.CODE_BLOCK_RE.search(text))


def collect_git_changed_paths() -> list[str]:
  """Return repo-relative paths from git diff when workspace is a git repo."""
  root = boost_config.WORKSPACE_ROOT.value
  if not root or not is_git_workspace(root):
    return []

  result = run_git_diff(root)
  if result is None:
    return []

  paths, _stat = result
  return paths


def collect_git_diff_context() -> str:
  """Return git diff --stat summary for audit context when workspace is a git repo."""
  root = boost_config.WORKSPACE_ROOT.value
  if not root or not is_git_workspace(root):
    return ""

  result = run_git_diff(root)
  if result is None:
    return ""

  paths, stat = result
  if not stat and not paths:
    return ""

  lines = ["<git_diff_stat>"]
  if stat:
    lines.append(stat)
  if paths:
    lines.append("")
    lines.append("Changed files:")
    for path in paths:
      lines.append(f"- {path}")
  lines.append("</git_diff_stat>")
  return "\n".join(lines)


def is_test_file(path: str) -> bool:
  """Return True when a repo-relative path looks like a test file."""
  normalized = path.replace("\\", "/")
  name = Path(normalized).name.lower()
  if name.startswith("test_") and name.endswith(".py"):
    return True
  if name.endswith("_test.py"):
    return True
  if ".test." in name or ".spec." in name:
    return True
  if "/__tests__/" in normalized or normalized.startswith("__tests__/"):
    return True
  return False


def merge_anchor_paths(cited_paths: list[str], git_paths: list[str] | None = None) -> list[str]:
  """Merge cited draft paths with git diff paths for nearby test discovery."""
  merged: list[str] = []
  seen: set[str] = set()
  for path in [*cited_paths, *(git_paths or collect_git_changed_paths())]:
    norm = deliverable.normalize_repo_path(path) or path
    if norm and norm not in seen:
      seen.add(norm)
      merged.append(norm)
  return merged


def _nearby_test_candidates(anchor: str) -> list[Path]:
  """Build heuristic candidate paths for tests related to an anchor file."""
  anchor_path = Path(anchor)
  stem = anchor_path.stem
  parent = anchor_path.parent
  candidates = [
    parent / f"test_{stem}.py",
    parent / f"{stem}_test.py",
    parent / "tests" / f"test_{stem}.py",
    parent / f"{stem}.test.ts",
    parent / f"{stem}.test.js",
    parent / f"{stem}.spec.ts",
    parent / f"{stem}.spec.js",
  ]

  parts = list(anchor_path.parts)
  if "src" in parts:
    src_index = parts.index("src")
    swapped = parts[:src_index] + ["tests"] + [f"test_{stem}.py"]
    candidates.append(Path(*swapped))

  tests_index = next((index for index, part in enumerate(parts) if part == "tests"), None)
  if tests_index is not None and tests_index + 1 < len(parts):
    module_stem = Path(parts[-1]).stem
    if module_stem.startswith("test_"):
      module_stem = module_stem[5:]
    source_parts = parts[:tests_index] + ["src"] + parts[tests_index + 1 : -1] + [
      f"{module_stem}.py",
    ]
    candidates.append(Path(*source_parts))

  return candidates


def find_nearby_test_files(anchor_paths: list[str], workspace_root: Path) -> list[str]:
  """Heuristically locate test files near changed or cited paths."""
  found: list[str] = []
  seen: set[str] = set()

  for anchor in anchor_paths:
    normalized = deliverable.normalize_repo_path(anchor) or anchor
    if is_test_file(normalized):
      target = workspace_root / normalized
      if target.is_file() and normalized not in seen:
        seen.add(normalized)
        found.append(normalized)
      continue

    for candidate in _nearby_test_candidates(normalized):
      rel = candidate.as_posix()
      if rel in seen:
        continue
      if (workspace_root / candidate).is_file():
        seen.add(rel)
        found.append(rel)

  return found


def _pyproject_has_pytest(content: str) -> bool:
  lowered = content.lower()
  return "[tool.pytest" in lowered or "pytest" in lowered


def _package_json_test_script(package_json: Path) -> str | None:
  try:
    data = json.loads(package_json.read_text(encoding="utf-8"))
  except (OSError, json.JSONDecodeError):
    return None

  scripts = data.get("scripts") or {}
  test_script = scripts.get("test")
  if not isinstance(test_script, str) or not test_script.strip():
    return None
  return test_script.strip()


def _search_roots_for_paths(
  anchor_paths: list[str],
  test_files: list[str],
  workspace_root: Path,
) -> list[Path]:
  roots: list[Path] = []
  seen: set[str] = set()

  for rel_path in [*anchor_paths, *test_files]:
    current = (workspace_root / rel_path).parent
    while True:
      try:
        current.relative_to(workspace_root)
      except ValueError:
        break
      key = str(current)
      if key not in seen:
        seen.add(key)
        roots.append(current)
      if current == workspace_root:
        break
      current = current.parent

  if workspace_root not in roots:
    roots.append(workspace_root)
  return roots


def suggest_test_command(
  test_files: list[str],
  anchor_paths: list[str],
  workspace_root: Path,
) -> str:
  """Infer a runnable test command from nearby pyproject.toml or package.json."""
  if not test_files:
    return ""

  search_roots = _search_roots_for_paths(anchor_paths, test_files, workspace_root)

  for start in search_roots:
    for parent in [start, *start.parents]:
      try:
        parent.relative_to(workspace_root)
      except ValueError:
        break

      package_json = parent / "package.json"
      if package_json.is_file() and _package_json_test_script(package_json):
        rel_parent = parent.relative_to(workspace_root)
        if rel_parent == Path("."):
          return "npm test"
        return f"cd {rel_parent.as_posix()} && npm test"

      pyproject = parent / "pyproject.toml"
      if pyproject.is_file():
        try:
          content = pyproject.read_text(encoding="utf-8")
        except OSError:
          content = ""
        if _pyproject_has_pytest(content):
          targets = " ".join(test_files[:3])
          rel_parent = parent.relative_to(workspace_root)
          if rel_parent == Path("."):
            return f"pytest {targets}"
          return f"cd {rel_parent.as_posix()} && pytest {targets}"

  return f"pytest {' '.join(test_files[:3])}"


def suggest_running_tests(cited_paths: list[str]) -> list[AuditFinding]:
  """Return a non-blocking warning when tests appear near changed paths."""
  root = boost_config.WORKSPACE_ROOT.value
  if not root:
    return []

  workspace_root = Path(root)
  anchor_paths = merge_anchor_paths(cited_paths)
  if not anchor_paths:
    return []

  test_files = find_nearby_test_files(anchor_paths, workspace_root)
  if not test_files:
    return []

  command = suggest_test_command(test_files, anchor_paths, workspace_root)
  preview = ", ".join(test_files[:3])
  if len(test_files) > 3:
    preview = f"{preview}, ..."

  return [
    AuditFinding(
      severity="warn",
      message=f"Consider running tests near changed paths ({preview})",
      fix_hint=f"Run: {command}" if command else "Run the project's test suite before shipping.",
    ),
  ]


def check_code_blocks_without_paths(
  draft: str,
  paths: list[str],
) -> list[AuditFinding]:
  """Flag drafts that include code fences but cite no target file paths."""
  if not draft_has_code_blocks(draft) or paths:
    return []

  return [
    AuditFinding(
      severity="major",
      message="Draft contains code blocks but cites no file paths",
      fix_hint="Name the target files for each code change.",
    ),
  ]


async def verify_draft_paths_exist(paths: list[str]) -> list[AuditFinding]:
  """Mechanically verify cited draft paths exist via read_workspace_file."""
  if not boost_config.WORKSPACE_ROOT.value or not paths:
    return []

  from modules.tools import read_workspace_file

  findings: list[AuditFinding] = []
  max_files = max(0, boost_config.AUTOCHECK_MAX_WORKSPACE_FILES.value)

  for path in paths[:max_files]:
    try:
      await read_workspace_file(path)
    except FileNotFoundError:
      findings.append(
        AuditFinding(
          severity="major",
          message=f"Referenced file does not exist in workspace: {path}",
          fix_hint="Use an existing repo-relative path or create the file explicitly.",
        ),
      )
    except Exception as exc:
      logger.debug(f"{ID_PREFIX}: skip path check for '{path}': {exc}")

  return findings


async def run_mechanical_preaudit(
  draft: str,
  paths: list[str],
) -> tuple[str, list[AuditFinding]]:
  """Run no-LLM pre-audit checks and return git context plus blocker findings."""
  git_context = collect_git_diff_context()
  findings: list[AuditFinding] = []

  findings.extend(check_code_blocks_without_paths(draft, paths))
  findings.extend(await verify_draft_paths_exist(paths))
  findings.extend(suggest_running_tests(paths))

  return git_context, findings


def apply_mechanical_findings(
  audit: AuditResult,
  mechanical_findings: list[AuditFinding],
) -> AuditResult:
  """Merge mechanical blockers into the audit result before delivery."""
  if not mechanical_findings:
    return audit

  findings = list(mechanical_findings) + list(audit.findings)
  verdict = audit.verdict
  if any(finding.severity in BLOCKING_SEVERITIES for finding in mechanical_findings):
    verdict = "revise"

  summary = audit.summary
  if verdict == "revise" and not summary:
    summary = "Mechanical pre-audit found blocking issues."

  return AuditResult(verdict=verdict, summary=summary, findings=findings)


def enrich_workspace_context(
  workspace_context: str,
  *,
  git_diff_context: str = "",
  mechanical_findings: list[AuditFinding] | None = None,
) -> str:
  """Append git diff and mechanical pre-audit notes to workspace audit context."""
  parts: list[str] = []
  if workspace_context:
    parts.append(workspace_context)
  if git_diff_context:
    parts.append(git_diff_context)
  if mechanical_findings:
    rendered = format_findings(
      AuditResult(verdict="revise", findings=mechanical_findings),
    )
    parts.append(f"<mechanical_preaudit>\n{rendered}\n</mechanical_preaudit>")

  return "\n\n".join(parts) if parts else ""


def enforce_workspace_evidence(
  audit: AuditResult,
  paths: list[str],
  workspace_context: str,
  tool_calls: list[dict],
) -> AuditResult:
  """
  Downgrade pass verdicts that lack workspace grounding when paths were cited.
  """
  if audit.verdict != "pass" or not requires_workspace_evidence(paths):
    return audit
  if workspace_evidence_satisfied(workspace_context, tool_calls):
    return audit

  findings = list(audit.findings)
  findings.append(
    AuditFinding(
      severity="major",
      message="Audit passed without workspace file evidence for cited paths",
      fix_hint="Read referenced workspace files before approving the draft.",
    )
  )
  return AuditResult(
    verdict="revise",
    summary=(
      audit.summary
      or "Workspace verification is required before shipping path-grounded answers."
    ),
    findings=findings,
  )


def format_findings(audit: AuditResult) -> str:
  if not audit.findings:
    return "No findings."

  lines = []
  for finding in audit.findings:
    hint = f" Fix: {finding.fix_hint}" if finding.fix_hint else ""
    lines.append(f"- [{finding.severity}] {finding.message}.{hint}")
  return "\n".join(lines)


def format_skipped_status(gate_reason: str) -> str:
  """Short status line for emit_status when autocheck passes through."""
  reason = (gate_reason or "unknown").strip()
  return f"Autocheck: skipped ({reason})"


def format_audit_status(audit: AuditResult) -> str:
  """Short status line for emit_status after an audit completes."""
  finding_count = len(audit.findings)
  noun = "finding" if finding_count == 1 else "findings"
  return f"Autocheck: {audit.verdict} ({finding_count} {noun})"


def format_audit_footer(audit: AuditResult) -> str:
  """Brief footer appended to the final answer when show_audit is enabled."""
  finding_count = len(audit.findings)
  noun = "finding" if finding_count == 1 else "findings"
  lines = [f"Autocheck: {audit.verdict} ({finding_count} {noun})"]

  summary = (audit.summary or "").strip()
  if summary:
    if len(summary) > 120:
      summary = summary[:117].rstrip() + "..."
    lines.append(summary)

  return "\n".join(lines)


def show_audit_footer(llm: "llm.LLM") -> bool:
  """Return True when show_audit is enabled via config or @boost_show_audit."""
  value = llm.boost_params.get("show_audit")
  if value is None:
    return boost_config.AUTOCHECK_SHOW_AUDIT.value
  if isinstance(value, bool):
    return value
  return str(value).strip().lower() in {"1", "true", "yes", "on"}


def append_audit_footer(final_text: str, audit: AuditResult) -> str:
  """Append a brief audit footer to the user-visible final answer."""
  footer = format_audit_footer(audit)
  if not footer:
    return final_text
  return f"{final_text.rstrip()}\n\n---\n*{footer}*"


def format_audit_artifact_html(audit: AuditResult) -> str:
  """Render a minimal HTML summary table for emit_artifact."""
  finding_count = len(audit.findings)
  noun = "finding" if finding_count == 1 else "findings"
  verdict_class = "verdict-pass" if audit.verdict == "pass" else "verdict-revise"
  summary = (audit.summary or "").strip()

  rows: list[str] = []
  if audit.findings:
    for finding in audit.findings:
      severity = html.escape(finding.severity)
      message = html.escape(finding.message)
      fix_hint = html.escape(finding.fix_hint or "—")
      rows.append(
        "<tr>"
        f'<td class="severity-{severity}">{severity}</td>'
        f"<td>{message}</td>"
        f"<td>{fix_hint}</td>"
        "</tr>",
      )
  else:
    rows.append('<tr><td colspan="3">No findings.</td></tr>')

  summary_html = ""
  if summary:
    summary_html = f"<p>{html.escape(summary)}</p>"

  return f"""
<style>
  .autocheck-audit {{
    font-family: system-ui, -apple-system, sans-serif;
    font-size: 14px;
    line-height: 1.4;
  }}
  .autocheck-audit table {{
    border-collapse: collapse;
    width: 100%;
    margin-top: 0.5rem;
  }}
  .autocheck-audit th,
  .autocheck-audit td {{
    border: 1px solid #d0d7de;
    padding: 6px 8px;
    text-align: left;
    vertical-align: top;
  }}
  .autocheck-audit th {{
    background: #f6f8fa;
  }}
  .autocheck-audit .verdict-pass {{ color: #1a7f37; font-weight: 600; }}
  .autocheck-audit .verdict-revise {{ color: #b54708; font-weight: 600; }}
  .autocheck-audit .severity-critical,
  .autocheck-audit .severity-major {{ color: #cf222e; }}
  .autocheck-audit .severity-warn {{ color: #9a6700; }}
</style>
<div class="autocheck-audit">
  <p>
    <strong>Autocheck:</strong>
    <span class="{verdict_class}">{html.escape(audit.verdict)}</span>
    ({finding_count} {noun})
  </p>
  {summary_html}
  <table>
    <thead>
      <tr>
        <th>Severity</th>
        <th>Finding</th>
        <th>Fix</th>
      </tr>
    </thead>
    <tbody>
      {"".join(rows)}
    </tbody>
  </table>
</div>
""".strip()


async def emit_audit_artifact(llm: "llm.LLM", audit: AuditResult) -> None:
  """Emit an HTML audit summary artifact when show_audit is enabled."""
  if not show_audit_footer(llm):
    return
  await llm.emit_artifact(format_audit_artifact_html(audit), wait=False)


async def generate_draft(chat: "ch.Chat", llm: "llm.LLM") -> str:
  draft = await llm.stream_chat_completion(
    prompt=DRAFT_PROMPT,
    conversation=str(chat),
    emit=False,
    params={"temperature": 0.2},
  )
  return (draft or "").strip()


def _register_workspace_tools() -> bool:
  if not boost_config.WORKSPACE_ROOT.value:
    return False

  from modules.tools import grep_workspace, list_workspace_files, read_workspace_file

  for name, tool in (
    ("read_workspace_file", read_workspace_file),
    ("grep_workspace", grep_workspace),
    ("list_workspace_files", list_workspace_files),
  ):
    try:
      tools.registry.set_local_tool(name, tool)
    except ValueError:
      pass
  return True


async def gather_workspace_context(paths: list[str]) -> str:
  """Read workspace files referenced in the draft."""
  if not boost_config.WORKSPACE_ROOT.value or not paths:
    return ""

  import research.fetch as fetch
  from modules.tools import _workspace_path

  chunks: list[str] = []
  max_files = max(0, boost_config.AUTOCHECK_MAX_WORKSPACE_FILES.value)
  max_chars = max(0, boost_config.AUTOCHECK_WORKSPACE_FILE_MAX_CHARS.value)

  for path in paths[:max_files]:
    try:
      target = _workspace_path(path)
      if not target.exists() or not target.is_file():
        raise FileNotFoundError(path)
      content = fetch.trim(target.read_text(encoding="utf-8"), max_chars)
      chunks.append(f'<file path="{path}">\n{content}\n</file>')
    except Exception as exc:
      logger.warning(f"{ID_PREFIX}: could not read workspace file '{path}': {exc}")
      chunks.append(f'<file path="{path}" error="{exc}" />')

  return "\n\n".join(chunks)


async def verify_symbols_with_grep(
  symbols: list[str],
  paths: list[str],
) -> str:
  """Mechanically verify draft symbols via grep_workspace."""
  if not boost_config.WORKSPACE_ROOT.value or not symbols:
    return ""

  from modules.tools import grep_workspace

  search_path = "."
  if paths:
    parent = Path(paths[0]).parent
    if str(parent) not in {"", "."}:
      search_path = str(parent)

  chunks: list[str] = []
  max_symbols = max(0, boost_config.AUTOCHECK_MAX_WORKSPACE_FILES.value)
  for symbol in symbols[:max_symbols]:
    try:
      result = await grep_workspace(
        re.escape(symbol),
        path=search_path,
        glob="*.py",
        max_matches=5,
      )
      chunks.append(
        f'<grep pattern="{symbol}" path="{search_path}">\n{result}\n</grep>',
      )
    except Exception as exc:
      logger.warning(f"{ID_PREFIX}: symbol grep failed for '{symbol}': {exc}")
      chunks.append(f'<grep pattern="{symbol}" error="{exc}" />')

  return "\n\n".join(chunks)


async def explore_workspace_with_tools(
  llm: "llm.LLM",
  draft: str,
  paths: list[str],
) -> tuple[str, list[dict]]:
  """Let the model verify paths via read_workspace_file when workspace is configured."""
  if not paths or not _register_workspace_tools():
    return "", []

  excerpt = draft[:4000]
  path_list = "\n".join(f"- {path}" for path in paths)
  history_before = len(llm.chat.history()) if getattr(llm, "chat", None) else 0

  try:
    notes = await llm.stream_chat_completion(
      prompt=WORKSPACE_EXPLORE_PROMPT,
      paths=path_list,
      draft_excerpt=excerpt,
      emit=False,
      params={"temperature": 0},
    )
    history_after = llm.chat.history()[history_before:] if getattr(llm, "chat", None) else []
    tool_calls = extract_workspace_tool_calls(history_after)
    return (notes or "").strip(), tool_calls
  except Exception as exc:
    logger.warning(f"{ID_PREFIX}: workspace exploration failed: {exc}")
    return f"Workspace exploration failed: {exc}", []


async def run_audit(
  chat: "ch.Chat",
  llm: "llm.LLM",
  draft: str,
  *,
  workspace_context: str = "",
  workspace_exploration: str = "",
  workspace_paths: list[str] | None = None,
  workspace_tool_calls: list[dict] | None = None,
  mechanical_findings: list[AuditFinding] | None = None,
  git_diff_context: str = "",
) -> tuple[AuditResult, AuditDebug]:
  enriched_context = enrich_workspace_context(
    workspace_context,
    git_diff_context=git_diff_context,
    mechanical_findings=mechanical_findings,
  )
  intermediate = orchestrate.cheap_llm(llm)
  result = await intermediate.chat_completion(
    prompt=AUDIT_PROMPT,
    conversation=str(chat),
    draft=draft,
    workspace_context=enriched_context or "No workspace context available.",
    workspace_exploration=workspace_exploration or "No workspace exploration performed.",
    schema=AuditResult,
    params={"temperature": 0},
    resolve=True,
  )

  if isinstance(result, dict):
    audit = AuditResult(**result)
  else:
    audit = AuditResult(verdict="pass", summary="Audit returned no structured result.")

  paths = workspace_paths or []
  tool_calls = workspace_tool_calls or []
  audit = apply_mechanical_findings(audit, mechanical_findings or [])
  audit = enforce_workspace_evidence(
    audit,
    paths,
    workspace_context,
    tool_calls,
  )

  debug = AuditDebug(
    triggered=True,
    gate_reason="triggered",
    tool_calls=tool_calls,
    verdict=audit.verdict,
  )
  logger.debug(f"{ID_PREFIX}: audit debug {debug.model_dump()}")
  return audit, debug


async def revise_draft(
  chat: "ch.Chat",
  llm: "llm.LLM",
  draft: str,
  audit: AuditResult,
) -> str:
  intermediate = orchestrate.cheap_llm(llm)
  revised = await intermediate.chat_completion(
    prompt=REVISE_PROMPT,
    conversation=str(chat),
    draft=draft,
    audit_summary=audit.summary or "Revise the draft to address audit findings.",
    findings=format_findings(audit),
    resolve=True,
    params={"temperature": 0.2},
  )
  return (revised or draft).strip()


async def emit_final(llm: "llm.LLM", final_text: str) -> None:
  if final_text:
    await llm.emit_message(final_text)


async def apply(chat: "ch.Chat", llm: "llm.LLM", config: dict | None = None):
  module_cfg = config or {}  # workflow module config; shadows name only in this block
  gate_reason = autocheck_gate_reason(chat)
  if gate_reason != "triggered":
    debug = AuditDebug(triggered=False, gate_reason=gate_reason, verdict="skipped")
    logger.debug(f"{ID_PREFIX}: Pass-through — {gate_reason} ({debug.model_dump()})")
    await llm.emit_status(format_skipped_status(gate_reason))
    return await workflow_mod.complete_or_defer(llm, module_cfg)

  message = orchestrate.last_user_text(chat)
  if not message:
    logger.warning(f"{ID_PREFIX}: No user message found, passing through")
    return await workflow_mod.complete_or_defer(llm, module_cfg)

  max_passes = max(0, boost_config.AUTOCHECK_MAX_PASSES.value)

  await llm.emit_status("Autocheck: drafting...")
  try:
    draft = await generate_draft(chat, llm)
  except Exception as exc:
    logger.error(f"{ID_PREFIX}: draft generation failed: {exc}")
    return await workflow_mod.complete_or_defer(llm, module_cfg)

  if not draft:
    logger.warning(f"{ID_PREFIX}: Empty draft, passing through")
    return await workflow_mod.complete_or_defer(llm, module_cfg)

  paths = extract_workspace_paths(message, draft)
  workspace_context = await gather_workspace_context(paths)

  await llm.emit_status("Autocheck: pre-audit checks...")
  git_diff_context, mechanical_findings = await run_mechanical_preaudit(draft, paths)

  await llm.emit_status("Autocheck: auditing...")
  workspace_exploration = ""
  workspace_tool_calls: list[dict] = []
  if boost_config.WORKSPACE_ROOT.value:
    symbols = extract_audit_symbols(message, draft)
    symbol_context = await verify_symbols_with_grep(symbols, paths)
    if symbol_context:
      workspace_exploration = symbol_context

    if paths:
      await llm.emit_status("Autocheck: verifying workspace paths...")
      exploration_notes, workspace_tool_calls = await explore_workspace_with_tools(
        llm,
        draft,
        paths,
      )
      if exploration_notes:
        workspace_exploration = (
          f"{workspace_exploration}\n\n{exploration_notes}".strip()
          if workspace_exploration
          else exploration_notes
        )

  try:
    audit, debug = await run_audit(
      chat,
      llm,
      draft,
      workspace_context=workspace_context,
      workspace_exploration=workspace_exploration,
      workspace_paths=paths,
      workspace_tool_calls=workspace_tool_calls,
      mechanical_findings=mechanical_findings,
      git_diff_context=git_diff_context,
    )
  except Exception as exc:
    logger.error(f"{ID_PREFIX}: audit failed: {exc}")
    await llm.emit_status("Autocheck: audit failed — delivering draft")
    await emit_final(llm, draft)
    return draft

  await llm.emit_status(format_audit_status(audit))

  final_text = draft
  passes_used = 0

  while should_revise(audit) and passes_used < max_passes:
    passes_used += 1
    await llm.emit_status(f"Autocheck: revising ({passes_used}/{max_passes})...")
    try:
      final_text = await revise_draft(chat, llm, final_text, audit)
      paths = extract_workspace_paths(message, final_text)
      git_diff_context, mechanical_findings = await run_mechanical_preaudit(
        final_text,
        paths,
      )
      audit, debug = await run_audit(
        chat,
        llm,
        final_text,
        workspace_context=workspace_context,
        workspace_exploration=workspace_exploration,
        workspace_paths=paths,
        workspace_tool_calls=workspace_tool_calls,
        mechanical_findings=mechanical_findings,
        git_diff_context=git_diff_context,
      )
      await llm.emit_status(format_audit_status(audit))
    except Exception as exc:
      logger.error(f"{ID_PREFIX}: revise pass failed: {exc}")
      break

  await emit_audit_artifact(llm, audit)
  if show_audit_footer(llm):
    final_text = append_audit_footer(final_text, audit)

  await llm.emit_status("Autocheck: final answer...")
  await emit_final(llm, final_text)
  return final_text