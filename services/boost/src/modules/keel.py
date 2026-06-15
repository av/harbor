"""Task anchor for multi-turn coding sessions in Harbor Boost."""

import json
import re
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

import chat as ch
import config as boost_config
import deliverable
import log
import research.debug_metrics as debug_metrics
import research.orchestrate as orchestrate
import research.workflow as workflow_mod
import tools.registry
from modules.diffscope import git_changed_paths, is_git_workspace
from state import request_set, request_store

if TYPE_CHECKING:
  import llm

ID_PREFIX = "keel"

DOCS = """
`keel` anchors multi-turn coding tasks so the model stays aligned with the
original objective. On the first substantive coding message it extracts a compact
`TaskBrief` (objective, constraints, acceptance criteria, in-scope paths) via a
cheap structured completion and stores it in request-scoped state.

On first extract it also serializes the brief into the chat as a hidden
`<keel_brief hidden="true">` system marker so the brief survives stateless proxy
restarts. Later requests re-hydrate from that marker when request state is empty.

On later turns it injects a compact `<task_anchor>` system block with the
objective, constraints, and the next unmet acceptance criterion. Anchor injection
is throttled to every N user turns (see `HARBOR_BOOST_KEEL_ANCHOR_EVERY`). Simple
drift heuristics flag scope-expansion phrases. Assistant messages are scanned for
simple keyword matches against each acceptance criterion; matched items show as
`[x]` in the landing checklist. A landing checklist with acceptance-criteria
checkboxes is injected when the user signals completion or when the model calls
the `finish` tool. When `HARBOR_BOOST_WORKSPACE_ROOT` is a
git repo, the checklist also lists `git diff --name-only` paths so the model can
compare workspace changes against acceptance criteria and in-scope paths.

**When to use**

- Multi-turn agentic coding where the model may drift from the original objective
- Long-running tasks with acceptance criteria and in-scope path constraints
- First substantive coding message extracts and stores a `TaskBrief`; later turns
  receive a compact `<task_anchor>` reminder

This is a minimal stub — not a full drift guard. Pair with `autocheck` for
deliverable verification or `diffscope` for file-scope enforcement.

**Parameters**

- `enabled` — when false, pass through without anchoring. Default: `true`
- `anchor_every` — inject `<task_anchor>` every N user turns (turn 1 never). Default: `2`
- `max_constraints` — maximum constraints listed in `<task_anchor>`. Default: `6`
- `keel_refresh` — when true, re-extract the `TaskBrief` from the current
  conversation and replace the hidden `<keel_brief>` marker. Resets met
  acceptance-criteria tracking. Default: `false`. Overridable per request via
  `@boost_keel_refresh`.

```bash
harbor boost modules add keel
harbor config set HARBOR_BOOST_KEEL_ENABLED true
```

**Workflow presets**

- `shipyard` — first step: task grounding before `caveman`, `tools`, `ponytail`, and `autocheck`

**Standalone**

```bash
docker run \\
  -e "HARBOR_BOOST_OPENAI_URLS=http://172.17.0.1:11434/v1" \\
  -e "HARBOR_BOOST_OPENAI_KEYS=sk-ollama" \\
  -e "HARBOR_BOOST_MODULES=keel" \\
  -p 8004:8000 \\
  ghcr.io/av/harbor-boost:latest
```
"""

logger = log.setup_logger(ID_PREFIX)

BRIEF_MARKER_TAG = "keel_brief"
BRIEF_MARKER_OPEN = f'<{BRIEF_MARKER_TAG} hidden="true">'
BRIEF_MARKER_CLOSE = f"</{BRIEF_MARKER_TAG}>"
BRIEF_MARKER_RE = re.compile(
  rf"<{BRIEF_MARKER_TAG}\s+hidden=\"true\">",
  re.IGNORECASE,
)

DRIFT_STATUS = "keel: scope expansion detected — deferring"
DRIFT_WARNING = (
  "<drift_warning>Scope expansion detected — stay on the anchored task.</drift_warning>"
)
LANDING_DRIFT_WARNING = (
  "<drift_warning>Scope expansion detected — confirm in-scope work only.</drift_warning>"
)

DRIFT_PHRASE_RE = re.compile(
  r"\b(?:"
  r"also\s+add|while\s+you(?:'re| are)\s+at\s+it|might\s+as\s+well|"
  r"additionally|expand\s+(?:the\s+)?scope|refactor\s+the\s+entire|"
  r"rewrite\s+everything|change\s+(?:the\s+)?architecture|bonus\s+feature|"
  r"extra\s+feature|one\s+more\s+thing|can\s+you\s+also|throw\s+in|"
  r"since\s+you(?:'re| are)\s+here|while\s+we(?:'re| are)\s+at\s+it"
  r")\b",
  re.IGNORECASE,
)

CRITERION_STOP_WORDS = frozenset({
  "a",
  "an",
  "and",
  "are",
  "as",
  "at",
  "be",
  "by",
  "can",
  "each",
  "for",
  "from",
  "has",
  "have",
  "in",
  "into",
  "is",
  "it",
  "its",
  "of",
  "on",
  "or",
  "should",
  "that",
  "the",
  "their",
  "them",
  "then",
  "this",
  "to",
  "was",
  "were",
  "when",
  "where",
  "which",
  "with",
  "without",
  "must",
  "all",
  "any",
  "not",
  "no",
})

CRITERION_TOKEN_RE = re.compile(
  r"[a-z0-9]+(?:\.[a-z0-9]+)+|[a-z0-9]+",
  re.IGNORECASE,
)

TASK_BRIEF_PROMPT = """
<instruction>
Extract a compact task brief from the user's latest coding request.
Capture the core objective, hard constraints, testable acceptance criteria,
and repo-relative paths that are in scope. Keep each field concise.
</instruction>

<conversation>
{conversation}
</conversation>

<latest_user_message>
{message}
</latest_user_message>
""".strip()


IMPLEMENTATION_BRIEF_RE = re.compile(
  r"\b(?:"
  r"implement|fix|debug|patch|refactor|rewrite|migrate|migrat|add|update|create|"
  r"write|build|ship|correct|repair"
  r")\b",
  re.IGNORECASE,
)


class TaskBrief(BaseModel):
  objective: str = Field(description="One-sentence goal for the coding task.")
  constraints: list[str] = Field(
    description="Hard limits the implementation must respect.",
    default_factory=list,
  )
  acceptance_criteria: list[str] = Field(
    description="Testable conditions that define done.",
    default_factory=list,
  )
  in_scope_paths: list[str] = Field(
    description="Repo-relative paths the work should touch.",
    default_factory=list,
  )


def is_implementation_brief(brief: TaskBrief | None) -> bool:
  """Return True when the keel brief anchors an implementation (not research) task."""
  if brief is None:
    return False

  objective = (brief.objective or "").strip()
  if objective and IMPLEMENTATION_BRIEF_RE.search(objective):
    return True

  for criterion in brief.acceptance_criteria or []:
    if IMPLEMENTATION_BRIEF_RE.search(criterion or ""):
      return True

  return False


def count_user_turns(chat: "ch.Chat") -> int:
  return len(chat.match(role="user"))


def is_substantive_message(text: str) -> bool:
  text = (text or "").strip()
  if not text or len(text) < 4:
    return False
  if deliverable.is_acknowledgment(text):
    return False
  return True


def is_done_signal(text: str) -> bool:
  return deliverable.has_explicit_done_signal(text)


def detect_drift(text: str, brief: TaskBrief | None = None) -> bool:
  """Return True when the user message suggests scope expansion."""
  text = (text or "").strip()
  if not text:
    return False
  if DRIFT_PHRASE_RE.search(text):
    return True

  if brief and brief.in_scope_paths:
    mentioned = deliverable.FILE_PATH_RE.findall(text)
    if mentioned:
      normalized_scope = {path.strip().lower() for path in brief.in_scope_paths}
      for raw in mentioned:
        path = deliverable.normalize_repo_path(raw).lower()
        if path and path not in normalized_scope:
          return True

  return False


def get_stored_brief() -> TaskBrief | None:
  stored = request_store("keel_task_brief", None)
  if stored is None:
    return None
  if isinstance(stored, TaskBrief):
    return stored
  return TaskBrief(**stored)


def store_brief(brief: TaskBrief) -> None:
  request_set("keel_task_brief", brief.model_dump())


def clear_brief_state() -> None:
  """Drop stored brief and met-criteria progress for a forced refresh."""
  request_set("keel_task_brief", None)
  request_set("keel_met_criteria", [])


def should_refresh_brief(llm: "llm.LLM") -> bool:
  """Return True when @boost_keel_refresh requests a brief re-extraction."""
  return debug_metrics.truthy_param(llm.boost_params.get("keel_refresh"))


def render_brief_marker(brief: TaskBrief, met_criteria: set[int] | None = None) -> str:
  payload = brief.model_dump()
  if met_criteria:
    payload["met_criteria"] = sorted(met_criteria)
  return (
    f'<{BRIEF_MARKER_TAG} hidden="true">\n'
    f"{json.dumps(payload, separators=(',', ':'))}\n"
    f"</{BRIEF_MARKER_TAG}>"
  )


def _brief_marker_payload(content: str) -> str | None:
  """Extract the JSON payload between hidden keel brief tags."""
  text = content or ""
  open_match = BRIEF_MARKER_RE.search(text)
  if not open_match:
    return None

  start = open_match.end()
  close_idx = text.lower().find(BRIEF_MARKER_CLOSE.lower(), start)
  if close_idx < 0:
    return None

  return text[start:close_idx].strip()


def parse_brief_marker(content: str) -> tuple[TaskBrief, set[int]] | None:
  payload_text = _brief_marker_payload(content)
  if not payload_text:
    return None

  try:
    payload = json.loads(payload_text)
  except json.JSONDecodeError:
    logger.warning(f"{ID_PREFIX}: invalid brief marker JSON")
    return None

  met_raw = payload.pop("met_criteria", [])
  try:
    brief = TaskBrief(**payload)
  except Exception as exc:
    logger.warning(f"{ID_PREFIX}: invalid brief marker payload: {exc}")
    return None

  met: set[int] = set()
  if isinstance(met_raw, list):
    for item in met_raw:
      try:
        met.add(int(item))
      except (TypeError, ValueError):
        continue

  return brief, met


def chat_has_brief_marker(chat: "ch.Chat") -> bool:
  for node in chat.plain():
    if node.role == "system" and _brief_marker_payload(node.content or ""):
      return True
  return False


def hydrate_brief_from_chat(chat: "ch.Chat") -> TaskBrief | None:
  for node in chat.plain():
    if node.role != "system":
      continue
    parsed = parse_brief_marker(node.content or "")
    if parsed is None:
      continue

    brief, met = parsed
    store_brief(brief)
    store_met_criteria(met)
    logger.info(
      f"{ID_PREFIX}: re-hydrated task brief from chat marker "
      f"({len(brief.acceptance_criteria)} criteria)"
    )
    return brief

  return None


def replace_brief_marker(chat: "ch.Chat", brief: TaskBrief) -> bool:
  """Replace an existing hidden brief marker in-place; return True when updated."""
  for node in chat.plain():
    if node.role != "system":
      continue
    if _brief_marker_payload(node.content or "") is None:
      continue

    met = get_met_criteria()
    node.content = render_brief_marker(brief, met)
    logger.debug(f"{ID_PREFIX}: replaced hidden brief marker in chat")
    return True

  return False


def inject_brief_marker(chat: "ch.Chat", brief: TaskBrief) -> None:
  if chat_has_brief_marker(chat):
    return

  met = get_met_criteria()
  chat.system(render_brief_marker(brief, met))
  logger.debug(f"{ID_PREFIX}: injected hidden brief marker into chat")


def upsert_brief_marker(chat: "ch.Chat", brief: TaskBrief, *, replace: bool = False) -> None:
  if replace and replace_brief_marker(chat, brief):
    return

  inject_brief_marker(chat, brief)


def should_inject_anchor(user_turns: int) -> bool:
  every = boost_config.KEEL_ANCHOR_EVERY.value
  if every < 1:
    every = 1
  return user_turns >= 2 and user_turns % every == 0


def get_met_criteria() -> set[int]:
  stored = request_store("keel_met_criteria", [])
  return set(stored)


def store_met_criteria(indices: set[int]) -> None:
  request_set("keel_met_criteria", sorted(indices))


def criterion_keywords(criterion: str) -> list[str]:
  """Extract significant tokens from an acceptance criterion for keyword matching."""
  text = (criterion or "").strip().lower()
  if not text:
    return []

  keywords: list[str] = []
  seen: set[str] = set()

  for match in deliverable.FILE_PATH_RE.finditer(text):
    path = deliverable.normalize_repo_path(match.group(0)).lower()
    if path and path not in seen:
      seen.add(path)
      keywords.append(path)

  for token in CRITERION_TOKEN_RE.findall(text):
    token = token.lower()
    if token.isdigit():
      if token not in seen:
        seen.add(token)
        keywords.append(token)
      continue
    if len(token) < 3 or token in CRITERION_STOP_WORDS:
      continue
    if token not in seen:
      seen.add(token)
      keywords.append(token)

  return keywords


def criterion_met_in_text(criterion: str, text: str) -> bool:
  """Return True when assistant text satisfies a criterion via substring or keywords."""
  criterion = (criterion or "").strip()
  text = (text or "").lower()
  if not criterion or not text:
    return False

  needle = criterion.lower()
  if len(needle) >= 12 and needle in text:
    return True

  keywords = criterion_keywords(criterion)
  if not keywords:
    return False

  return all(keyword in text for keyword in keywords)


def update_met_criteria_from_history(chat: "ch.Chat", brief: TaskBrief) -> set[int]:
  met = get_met_criteria()
  if not brief.acceptance_criteria:
    return met

  assistant_text = " ".join(
    (node.content or "")
    for node in chat.match(role="assistant")
  )

  changed = False
  for index, criterion in enumerate(brief.acceptance_criteria):
    if index in met:
      continue
    if criterion_met_in_text(criterion, assistant_text):
      met.add(index)
      changed = True

  store_met_criteria(met)
  if changed:
    logger.debug(
      f"{ID_PREFIX}: met criteria updated to {sorted(met)} "
      f"({len(met)}/{len(brief.acceptance_criteria)})"
    )
  return met


def sync_met_criteria_marker(chat: "ch.Chat", brief: TaskBrief) -> None:
  """Persist met-criteria progress into the hidden brief marker when present."""
  if chat_has_brief_marker(chat):
    replace_brief_marker(chat, brief)


def next_unmet_criterion(brief: TaskBrief, met: set[int]) -> str | None:
  for index, criterion in enumerate(brief.acceptance_criteria):
    if index not in met:
      return criterion
  return None


ANCHOR_MAX_LINES = 8
ANCHOR_MAX_TEXT_LEN = 120
ANCHOR_MAX_CONSTRAINT_LEN = 80
ANCHOR_MAX_PATHS = 5


def _truncate_anchor_text(text: str, max_len: int = ANCHOR_MAX_TEXT_LEN) -> str:
  text = (text or "").strip()
  if len(text) <= max_len:
    return text
  return text[: max_len - 1].rstrip() + "…"


def _format_anchor_constraints(constraints: list[str] | None) -> str:
  items = constraints or ["Stay within the stated scope."]
  max_count = boost_config.KEEL_MAX_CONSTRAINTS.value
  if max_count < 1:
    max_count = 1
  shown = items[:max_count]
  truncated = [_truncate_anchor_text(item, ANCHOR_MAX_CONSTRAINT_LEN) for item in shown]
  if len(items) > max_count:
    truncated.append(f"+{len(items) - max_count} more")
  return "; ".join(truncated)


def _format_anchor_paths(paths: list[str]) -> str:
  shown = paths[:ANCHOR_MAX_PATHS]
  formatted = [_truncate_anchor_text(path, 60) for path in shown]
  if len(paths) > ANCHOR_MAX_PATHS:
    formatted.append(f"+{len(paths) - ANCHOR_MAX_PATHS} more")
  return ", ".join(formatted)


def render_anchor_block(brief: TaskBrief, next_criterion: str | None = None) -> str:
  lines = [
    "<task_anchor>",
    f"<objective>{_truncate_anchor_text(brief.objective)}</objective>",
    f"<constraints>{_format_anchor_constraints(brief.constraints)}</constraints>",
  ]

  if next_criterion:
    lines.append(
      f"<next_criterion>{_truncate_anchor_text(next_criterion)}</next_criterion>"
    )

  if brief.in_scope_paths:
    lines.append(f"<in_scope_paths>{_format_anchor_paths(brief.in_scope_paths)}</in_scope_paths>")

  lines.append("</task_anchor>")
  return "\n".join(lines)


def collect_landing_git_changes() -> str:
  """Return git diff --name-only block for the landing checklist when workspace is a git repo."""
  root = boost_config.WORKSPACE_ROOT.value
  if not root or not is_git_workspace(root):
    return ""

  paths = git_changed_paths(root)
  if not paths:
    return ""

  lines = [
    "<git_changed_files>",
    "Workspace changes (git diff --name-only) — compare against acceptance criteria:",
  ]
  lines.extend(f"- {path}" for path in paths)
  lines.append("</git_changed_files>")
  return "\n".join(lines)


def render_landing_checklist(brief: TaskBrief, *, drift_detected: bool = False) -> str:
  criteria = brief.acceptance_criteria or ["Task completed as requested."]
  met = get_met_criteria()
  met_count = sum(1 for index in range(len(criteria)) if index in met)
  total = len(criteria)

  lines = [
    "<landing_checklist>",
    f"<objective>{brief.objective}</objective>",
    f'<acceptance_criteria status="{met_count}/{total} met">',
    "Before finishing, confirm each acceptance criterion:",
  ]

  for index, criterion in enumerate(criteria):
    mark = "x" if index in met else " "
    lines.append(f"- [{mark}] {criterion}")

  lines.append("</acceptance_criteria>")

  git_changes = collect_landing_git_changes()
  if git_changes:
    lines.append(git_changes)

  if brief.in_scope_paths:
    lines.append("<in_scope_paths>")
    lines.extend(f"- {path}" for path in brief.in_scope_paths)
    lines.append("</in_scope_paths>")

  if drift_detected:
    lines.append(LANDING_DRIFT_WARNING)

  lines.extend([
    "<reminder>Verify each acceptance criterion before finishing.</reminder>",
    "</landing_checklist>",
  ])
  return "\n".join(lines)


def needs_keel(chat: "ch.Chat") -> bool:
  return keel_gate_reason(chat) == "triggered"


def keel_gate_reason(
  chat: "ch.Chat",
  *,
  brief: TaskBrief | None = None,
) -> str:
  """Return ``triggered`` when keel should anchor this turn, else a pass-through reason."""
  if not boost_config.KEEL_ENABLED.value:
    return "disabled"
  if brief is not None:
    return "triggered"
  if getattr(chat, "llm", None) and getattr(chat.llm, "module", None) == ID_PREFIX:
    return "triggered"
  if deliverable.is_coding_deliverable(chat):
    return "triggered"
  return "not_coding_deliverable"


async def extract_task_brief(
  chat: "ch.Chat",
  llm: "llm.LLM",
  message: str,
) -> TaskBrief:
  intermediate = orchestrate.cheap_llm(llm)
  result = await intermediate.chat_completion(
    prompt=TASK_BRIEF_PROMPT,
    conversation=str(chat),
    message=message,
    schema=TaskBrief,
    params={"temperature": 0},
    resolve=True,
  )

  if isinstance(result, dict):
    return TaskBrief(**result)

  return TaskBrief(
    objective=message[:240],
    acceptance_criteria=["Implementation matches the user request."],
    in_scope_paths=_fallback_paths(message),
  )


def _fallback_paths(message: str) -> list[str]:
  paths: list[str] = []
  seen: set[str] = set()
  for match in deliverable.FILE_PATH_RE.finditer(message):
    path = deliverable.normalize_repo_path(match.group(0))
    if path and path not in seen:
      seen.add(path)
      paths.append(path)
  return paths


async def ensure_task_brief(
  chat: "ch.Chat",
  llm: "llm.LLM",
  message: str,
  *,
  force_refresh: bool = False,
) -> TaskBrief | None:
  if not force_refresh:
    existing = get_stored_brief()
    if existing is not None:
      return existing

  if not is_substantive_message(message):
    return None

  try:
    brief = await extract_task_brief(chat, llm, message)
  except Exception as exc:
    logger.error(f"{ID_PREFIX}: task brief extraction failed: {exc}")
    brief = TaskBrief(
      objective=message[:240] or "Complete the coding task.",
      constraints=["Stay within the original request."],
      acceptance_criteria=["Implementation matches the user request."],
      in_scope_paths=_fallback_paths(message),
    )

  if not brief.in_scope_paths:
    brief.in_scope_paths = _fallback_paths(message)

  if force_refresh:
    store_met_criteria(set())

  store_brief(brief)
  upsert_brief_marker(chat, brief, replace=force_refresh)
  action = "refreshed" if force_refresh else "stored"
  logger.info(
    f"{ID_PREFIX}: {action} task brief with {len(brief.acceptance_criteria)} criteria"
  )
  return brief


def _register_finish_wrapper(
  chat: "ch.Chat",
  brief: TaskBrief,
  drift_detected: bool,
) -> None:
  async def finish(answer: str) -> str:
    """
    Return the final answer when the model is done using tools.
    Keel prepends a landing checklist so the model verifies acceptance criteria.

    Args:
      answer (str): Final answer to provide to the user.
    """
    update_met_criteria_from_history(chat, brief)
    sync_met_criteria_marker(chat, brief)
    checklist = render_landing_checklist(brief, drift_detected=drift_detected)
    logger.info(f"{ID_PREFIX}: landing checklist on finish")
    return f"{checklist}\n\n{answer}"

  try:
    tools.registry.set_local_tool("finish", finish)
  except ValueError:
    logger.debug(f"{ID_PREFIX}: finish tool already registered, skipping wrapper")


async def apply(chat: "ch.Chat", llm: "llm.LLM", config: dict | None = None):
  timer = debug_metrics.DebugTimer()
  extra_calls = 0
  message = orchestrate.last_user_text(chat)
  if not message:
    logger.warning(f"{ID_PREFIX}: No user message found, passing through")
    debug_metrics.record_module(
      ID_PREFIX,
      debug_metrics.skipped_payload("empty_message", duration_ms=timer.elapsed_ms()),
      logger=logger,
    )
    return await workflow_mod.complete_or_defer(llm, config)

  force_refresh = should_refresh_brief(llm)
  if force_refresh:
    clear_brief_state()
    brief = None
  else:
    brief = get_stored_brief() or hydrate_brief_from_chat(chat)

  gate_reason = keel_gate_reason(chat, brief=brief)
  if gate_reason != "triggered":
    debug_metrics.record_module(
      ID_PREFIX,
      debug_metrics.skipped_payload(
        gate_reason,
        duration_ms=timer.elapsed_ms(),
        extra_calls=extra_calls,
      ),
      logger=logger,
      gate_reason=gate_reason,
    )
    return await workflow_mod.complete_or_defer(llm, config)

  user_turns = count_user_turns(chat)
  drift_detected = False
  extracted_brief = False
  anchor_injected = False
  landing_injected = False

  if (brief is None or force_refresh) and is_substantive_message(message):
    if force_refresh:
      await llm.emit_status("Keel: refreshing task brief...")
    else:
      await llm.emit_status("Keel: extracting task brief...")
    brief = await ensure_task_brief(chat, llm, message, force_refresh=force_refresh)
    if brief is not None:
      extracted_brief = True
      extra_calls += 1

  if brief is None:
    debug_metrics.record_module(
      ID_PREFIX,
      debug_metrics.skipped_payload(
        "non_substantive_message",
        duration_ms=timer.elapsed_ms(),
        extra_calls=extra_calls,
      ),
      logger=logger,
      gate_reason="non_substantive_message",
    )
    return await workflow_mod.complete_or_defer(llm, config)

  met = update_met_criteria_from_history(chat, brief)
  sync_met_criteria_marker(chat, brief)

  if user_turns >= 2:
    drift_detected = detect_drift(message, brief)
    if drift_detected:
      logger.warning(f"{ID_PREFIX}: scope drift detected on turn {user_turns}")
      await llm.emit_status(DRIFT_STATUS)
      chat.system(DRIFT_WARNING)

    if should_inject_anchor(user_turns):
      next_criterion = next_unmet_criterion(brief, met)
      chat.system(render_anchor_block(brief, next_criterion))
      anchor_injected = True
      logger.debug(
        f"{ID_PREFIX}: injected anchor on turn {user_turns}"
        + (f", next criterion: {next_criterion[:60]}" if next_criterion else ", all criteria met")
      )
    else:
      logger.debug(
        f"{ID_PREFIX}: skipped anchor on turn {user_turns} "
        f"(every {boost_config.KEEL_ANCHOR_EVERY.value} turns)"
      )

  if is_done_signal(message):
    met = update_met_criteria_from_history(chat, brief)
    sync_met_criteria_marker(chat, brief)
    logger.info(f"{ID_PREFIX}: done signal detected, injecting landing checklist")
    chat.system(render_landing_checklist(brief, drift_detected=drift_detected))
    landing_injected = True

  _register_finish_wrapper(chat, brief, drift_detected)
  debug_metrics.record_module(
    ID_PREFIX,
    debug_metrics.triggered_payload(
      "triggered",
      duration_ms=timer.elapsed_ms(),
      extra_calls=extra_calls,
      user_turns=user_turns,
      extracted_brief=extracted_brief,
      anchor_injected=anchor_injected,
      landing_injected=landing_injected,
      drift_detected=drift_detected,
    ),
    logger=logger,
  )
  return await workflow_mod.complete_or_defer(llm, config)