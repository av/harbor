"""Selective post-deliverable self-check for Harbor Boost."""

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

import chat as ch
import config
import deliverable
import log
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
coding work. Simple acknowledgments (`thanks`, `ok`, `continue`) and very short
messages are always skipped.

When `HARBOR_BOOST_WORKSPACE_ROOT` is set and paths are cited, the audit cannot
return `pass` without workspace evidence — either direct `read_workspace_file`
reads, `grep_workspace` symbol checks, `list_workspace_files` directory scans, or
tool calls during workspace exploration.

Before the LLM audit, mechanical pre-checks (no model call) run when a workspace
is configured:

- **Git diff context** — in a git repo, `git diff --stat` is included in audit context
- **Path existence** — cited draft paths are verified with `read_workspace_file`
- **Code block grounding** — drafts with fenced code but zero file paths are flagged

Mechanical findings are structured blockers merged into the audit before delivery.
Audit debug logs include `triggered`, `gate_reason`, `tool_calls`, and `verdict`
for troubleshooting.

**Parameters**

- `enabled` — when false, pass through without auditing. Default: `true`
- `max_passes` — maximum audit-and-revise passes. Default: `1`
- `max_workspace_files` — workspace files read per request. Default: `5`
- `workspace_file_max_chars` — characters per workspace file. Default: `50000`
- `@boost_show_audit` — when true, append a brief audit footer to the final answer

```bash
harbor boost modules add autocheck
harbor config set HARBOR_BOOST_AUTOCHECK_ENABLED true
harbor config set HARBOR_BOOST_AUTOCHECK_MAX_PASSES 1
harbor config set HARBOR_BOOST_WORKSPACE_ROOT /workspace/myproject
```

**Workflow presets**

- `code-check` (`tools`, `autocheck`, `final`) — self-audit coding deliverables
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

CONTINUATION_RE = re.compile(
  r"\b(?:continue|keep\s+going|go\s+on|proceed|carry\s+on|as\s+planned|same\s+as\s+before)\b",
  re.IGNORECASE,
)

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
  severity: Literal["critical", "major", "minor", "info"] = Field(
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


def _last_user_text(chat: "ch.Chat") -> str:
  node = chat.match_one(role="user", index=-1)
  return (node.content or "").strip() if node else ""


def autocheck_gate_reason(chat: "ch.Chat") -> str:
  """Explain why autocheck would or would not run on this turn."""
  if not config.AUTOCHECK_ENABLED.value:
    return "disabled"

  text = _last_user_text(chat)
  if not text:
    return "empty_message"
  if deliverable.is_completion_trigger(chat):
    return "triggered"
  if deliverable.is_acknowledgment(text):
    return "acknowledgment"
  if len(text) < MIN_AUTOCHECK_MESSAGE_CHARS:
    return "short_message"
  if CONTINUATION_RE.search(text) and len(text) < 120:
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

  limit = max(0, config.AUTOCHECK_MAX_WORKSPACE_FILES.value)
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


def _cheap_llm(llm: "llm.LLM") -> "llm.LLM":
  """Bare downstream client for inexpensive internal completions."""
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
  return bool(config.WORKSPACE_ROOT.value and paths)


def draft_has_code_blocks(text: str) -> bool:
  """Return True when the draft contains fenced code blocks."""
  return bool(deliverable.CODE_BLOCK_RE.search(text))


def collect_git_diff_context() -> str:
  """Return git diff --stat summary for audit context when workspace is a git repo."""
  root = config.WORKSPACE_ROOT.value
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
  if not config.WORKSPACE_ROOT.value or not paths:
    return []

  from modules.tools import read_workspace_file

  findings: list[AuditFinding] = []
  max_files = max(0, config.AUTOCHECK_MAX_WORKSPACE_FILES.value)

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
  """Return True when @boost_show_audit requests an audit footer."""
  value = llm.boost_params.get("show_audit")
  if isinstance(value, bool):
    return value
  if value is None:
    return False
  return str(value).strip().lower() in {"1", "true", "yes", "on"}


def append_audit_footer(final_text: str, audit: AuditResult) -> str:
  """Append a brief audit footer to the user-visible final answer."""
  footer = format_audit_footer(audit)
  if not footer:
    return final_text
  return f"{final_text.rstrip()}\n\n---\n*{footer}*"


async def generate_draft(chat: "ch.Chat", llm: "llm.LLM") -> str:
  draft = await llm.stream_chat_completion(
    prompt=DRAFT_PROMPT,
    conversation=str(chat),
    emit=False,
    params={"temperature": 0.2},
  )
  return (draft or "").strip()


def _register_workspace_tools() -> bool:
  if not config.WORKSPACE_ROOT.value:
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
  if not config.WORKSPACE_ROOT.value or not paths:
    return ""

  import research.fetch as fetch
  from modules.tools import _workspace_path

  chunks: list[str] = []
  max_files = max(0, config.AUTOCHECK_MAX_WORKSPACE_FILES.value)
  max_chars = max(0, config.AUTOCHECK_WORKSPACE_FILE_MAX_CHARS.value)

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
  if not config.WORKSPACE_ROOT.value or not symbols:
    return ""

  from modules.tools import grep_workspace

  search_path = "."
  if paths:
    parent = Path(paths[0]).parent
    if str(parent) not in {"", "."}:
      search_path = str(parent)

  chunks: list[str] = []
  max_symbols = max(0, config.AUTOCHECK_MAX_WORKSPACE_FILES.value)
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
  intermediate = _cheap_llm(llm)
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
  intermediate = _cheap_llm(llm)
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


async def apply(chat: "ch.Chat", llm: "llm.LLM"):
  gate_reason = autocheck_gate_reason(chat)
  if gate_reason != "triggered":
    debug = AuditDebug(triggered=False, gate_reason=gate_reason, verdict="skipped")
    logger.debug(f"{ID_PREFIX}: Pass-through — {gate_reason} ({debug.model_dump()})")
    return await llm.stream_final_completion()

  message = _last_user_text(chat)
  if not message:
    logger.warning(f"{ID_PREFIX}: No user message found, passing through")
    return await llm.stream_final_completion()

  max_passes = max(0, config.AUTOCHECK_MAX_PASSES.value)

  await llm.emit_status("Autocheck: drafting...")
  try:
    draft = await generate_draft(chat, llm)
  except Exception as exc:
    logger.error(f"{ID_PREFIX}: draft generation failed: {exc}")
    return await llm.stream_final_completion()

  if not draft:
    logger.warning(f"{ID_PREFIX}: Empty draft, passing through")
    return await llm.stream_final_completion()

  paths = extract_workspace_paths(message, draft)
  workspace_context = await gather_workspace_context(paths)

  await llm.emit_status("Autocheck: pre-audit checks...")
  git_diff_context, mechanical_findings = await run_mechanical_preaudit(draft, paths)

  await llm.emit_status("Autocheck: auditing...")
  workspace_exploration = ""
  workspace_tool_calls: list[dict] = []
  if config.WORKSPACE_ROOT.value:
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

  if show_audit_footer(llm):
    final_text = append_audit_footer(final_text, audit)

  await llm.emit_status("Autocheck: final answer...")
  await emit_final(llm, final_text)
  return final_text