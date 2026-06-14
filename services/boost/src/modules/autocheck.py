"""Selective post-deliverable self-check for Harbor Boost."""

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

When `HARBOR_BOOST_WORKSPACE_ROOT` is set, the audit verifies referenced file
paths against the workspace and may call `read_workspace_file` during exploration.

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


def _last_user_text(chat: "ch.Chat") -> str:
  node = chat.match_one(role="user", index=-1)
  return (node.content or "").strip() if node else ""


def needs_autocheck(chat: "ch.Chat") -> bool:
  """Return True when this turn should run post-deliverable self-check."""
  if not config.AUTOCHECK_ENABLED.value:
    return False
  return deliverable.is_coding_deliverable(chat)


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
) -> str:
  """Let the model verify paths via read_workspace_file when workspace is configured."""
  if not paths or not _register_workspace_tool():
    return ""

  excerpt = draft[:4000]
  path_list = "\n".join(f"- {path}" for path in paths)

  try:
    notes = await llm.stream_chat_completion(
      prompt=WORKSPACE_EXPLORE_PROMPT,
      paths=path_list,
      draft_excerpt=excerpt,
      emit=False,
      params={"temperature": 0},
    )
    return (notes or "").strip()
  except Exception as exc:
    logger.warning(f"{ID_PREFIX}: workspace exploration failed: {exc}")
    return f"Workspace exploration failed: {exc}"


async def run_audit(
  chat: "ch.Chat",
  llm: "llm.LLM",
  draft: str,
  *,
  workspace_context: str = "",
  workspace_exploration: str = "",
) -> AuditResult:
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
    return AuditResult(**result)
  return AuditResult(verdict="pass", summary="Audit returned no structured result.")


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
  if not needs_autocheck(chat):
    logger.debug(f"{ID_PREFIX}: Pass-through — not a coding deliverable turn")
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
  if config.WORKSPACE_ROOT.value and paths:
    await llm.emit_status("Autocheck: verifying workspace paths...")
    workspace_exploration = await explore_workspace_with_tools(llm, draft, paths)

  try:
    audit = await run_audit(
      chat,
      llm,
      draft,
      workspace_context=workspace_context,
      workspace_exploration=workspace_exploration,
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
      audit = await run_audit(
        chat,
        llm,
        final_text,
        workspace_context=workspace_context,
        workspace_exploration=workspace_exploration,
      )
    except Exception as exc:
      logger.error(f"{ID_PREFIX}: revise pass failed: {exc}")
      break

  await llm.emit_status("Autocheck: final answer...")
  await emit_final(llm, final_text)
  return final_text