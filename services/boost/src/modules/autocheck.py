"""Selective post-deliverable self-check for Harbor Boost."""

import json
import re
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

import chat as ch
import config
import deliverable
import log
import tools.registry

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

Autocheck triggers only when the latest user message carries **at least two**
deliverable signals (for example a coding keyword plus a repo-relative file path).
Simple acknowledgments (`thanks`, `ok`, `continue`) and very short messages are
always skipped.

When `HARBOR_BOOST_WORKSPACE_ROOT` is set and paths are cited, the audit cannot
return `pass` without workspace evidence — either direct `read_workspace_file`
reads or tool calls during workspace exploration. Audit debug logs include
`triggered`, `gate_reason`, `tool_calls`, and `verdict` for troubleshooting.

**Parameters**

- `enabled` — when false, pass through without auditing. Default: `true`
- `max_passes` — maximum audit-and-revise passes. Default: `1`
- `max_workspace_files` — workspace files read per request. Default: `5`
- `workspace_file_max_chars` — characters per workspace file. Default: `50000`

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

SKIP_MESSAGE_RE = re.compile(
  r"^\s*(?:"
  r"thanks?(?:\s+you)?|thank\s+you|thx|ok(?:ay)?|cool|great|perfect|sounds?\s+good|"
  r"got\s+it|understood|yes|no|yep|nope|sure|continue|go\s+on|go\s+ahead|"
  r"proceed|keep\s+going|lgtm|looks?\s+good|done|next|ship\s+it"
  r")\s*[.!]?\s*$",
  re.IGNORECASE,
)
CONTINUATION_RE = re.compile(
  r"\b(?:continue|keep\s+going|go\s+on|proceed|carry\s+on|as\s+planned|same\s+as\s+before)\b",
  re.IGNORECASE,
)

BACKTICK_PATH_RE = re.compile(
  r"`((?:[\w.-]+/)+[\w.-]+\.(?:py|ts|tsx|js|jsx|go|rs|java|rb|php|cs|cpp|c|h|hpp|swift|kt|scala|sql|yaml|yml|toml|json|md|sh|bash|zsh|dockerfile|makefile))`",
  re.IGNORECASE,
)

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


def _normalize_path(raw: str) -> str:
  return re.sub(r"^[\s`'\"(]+", "", (raw or "").strip()).rstrip("`'\"")


def extract_workspace_paths(*texts: str) -> list[str]:
  """Collect unique repo-relative paths mentioned in draft or user text."""
  paths: list[str] = []
  seen: set[str] = set()

  for text in texts:
    if not text:
      continue

    for match in deliverable.FILE_PATH_RE.finditer(text):
      path = _normalize_path(match.group(0))
      if path and path not in seen:
        seen.add(path)
        paths.append(path)

    for match in BACKTICK_PATH_RE.finditer(text):
      path = _normalize_path(match.group(1))
      if path and path not in seen:
        seen.add(path)
        paths.append(path)

  limit = max(0, config.AUTOCHECK_MAX_WORKSPACE_FILES.value)
  return paths[:limit] if limit else []


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
  """Collect read_workspace_file tool calls from a chat history slice."""
  calls: list[dict] = []
  for message in messages:
    for tool_call in message.get("tool_calls") or []:
      function = tool_call.get("function") or {}
      if function.get("name") != "read_workspace_file":
        continue

      args_raw = function.get("arguments") or "{}"
      try:
        args = json.loads(args_raw) if args_raw.strip() else {}
      except json.JSONDecodeError:
        args = {"raw_arguments": args_raw}

      calls.append({
        "name": "read_workspace_file",
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
    path = (args.get("path") or "").strip()
    if path and path not in seen:
      seen.add(path)
      paths.append(path)

  return paths


def requires_workspace_evidence(paths: list[str]) -> bool:
  return bool(config.WORKSPACE_ROOT.value and paths)


def enforce_workspace_evidence(
  audit: AuditResult,
  paths: list[str],
  evidence_paths: list[str],
) -> AuditResult:
  """
  Downgrade pass verdicts that lack workspace grounding when paths were cited.
  """
  if audit.verdict != "pass" or not requires_workspace_evidence(paths):
    return audit
  if evidence_paths:
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


async def generate_draft(chat: "ch.Chat", llm: "llm.LLM") -> str:
  draft = await llm.stream_chat_completion(
    prompt=DRAFT_PROMPT,
    conversation=str(chat),
    emit=False,
    params={"temperature": 0.2},
  )
  return (draft or "").strip()


def _register_workspace_tool() -> bool:
  if not config.WORKSPACE_ROOT.value:
    return False

  from modules.tools import read_workspace_file

  try:
    tools.registry.set_local_tool("read_workspace_file", read_workspace_file)
  except ValueError:
    pass
  return True


async def gather_workspace_context(paths: list[str]) -> str:
  """Read workspace files referenced in the draft."""
  if not config.WORKSPACE_ROOT.value or not paths:
    return ""

  from modules.tools import read_workspace_file

  chunks: list[str] = []
  max_files = max(0, config.AUTOCHECK_MAX_WORKSPACE_FILES.value)

  for path in paths[:max_files]:
    try:
      content = await read_workspace_file(path)
      chunks.append(f'<file path="{path}">\n{content}\n</file>')
    except Exception as exc:
      logger.warning(f"{ID_PREFIX}: could not read workspace file '{path}': {exc}")
      chunks.append(f'<file path="{path}" error="{exc}" />')

  return "\n\n".join(chunks)


async def explore_workspace_with_tools(
  llm: "llm.LLM",
  draft: str,
  paths: list[str],
) -> tuple[str, list[dict]]:
  """Let the model verify paths via read_workspace_file when workspace is configured."""
  if not paths or not _register_workspace_tool():
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
) -> tuple[AuditResult, AuditDebug]:
  intermediate = _cheap_llm(llm)
  result = await intermediate.chat_completion(
    prompt=AUDIT_PROMPT,
    conversation=str(chat),
    draft=draft,
    workspace_context=workspace_context or "No workspace context available.",
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
  evidence_paths = workspace_evidence_paths(workspace_context, tool_calls)
  audit = enforce_workspace_evidence(audit, paths, evidence_paths)

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

  await llm.emit_status("Autocheck: auditing...")
  workspace_exploration = ""
  workspace_tool_calls: list[dict] = []
  if config.WORKSPACE_ROOT.value and paths:
    await llm.emit_status("Autocheck: verifying workspace paths...")
    workspace_exploration, workspace_tool_calls = await explore_workspace_with_tools(
      llm,
      draft,
      paths,
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
    )
  except Exception as exc:
    logger.error(f"{ID_PREFIX}: audit failed: {exc}")
    await llm.emit_status("Autocheck: final answer...")
    await emit_final(llm, draft)
    return draft

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
      )
    except Exception as exc:
      logger.error(f"{ID_PREFIX}: revise pass failed: {exc}")
      break

  await llm.emit_status("Autocheck: final answer...")
  await emit_final(llm, final_text)
  return final_text