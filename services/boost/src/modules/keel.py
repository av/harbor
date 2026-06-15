"""Task anchor for multi-turn coding sessions in Harbor Boost."""

import json
import re
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

import chat as ch
import config as boost_config
import deliverable
import log
import research.workflow as workflow_mod
import tools.registry
from state import request as request_state

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
drift heuristics flag scope-expansion phrases. A landing checklist with
acceptance-criteria checkboxes is injected when the user signals completion or
when the model calls the `finish` tool.

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

SKIP_MESSAGE_RE = re.compile(
  r"^\s*(?:"
  r"thanks?(?:\s+you)?|thank\s+you|thx|ok(?:ay)?|cool|great|perfect|sounds?\s+good|"
  r"got\s+it|understood|yes|no|yep|nope|sure|continue|go\s+on|go\s+ahead|"
  r"proceed|keep\s+going|lgtm|looks?\s+good|next"
  r")\s*[.!]?\s*$",
  re.IGNORECASE,
)

BRIEF_MARKER_TAG = "keel_brief"
BRIEF_MARKER_OPEN = f'<{BRIEF_MARKER_TAG} hidden="true">'
BRIEF_MARKER_CLOSE = f"</{BRIEF_MARKER_TAG}>"
BRIEF_MARKER_RE = re.compile(
  rf"<{BRIEF_MARKER_TAG}\s+hidden=\"true\">",
  re.IGNORECASE,
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


def _request_store(name: str, default):
  request = request_state.get()
  if request is None:
    return default

  if not hasattr(request.state, name):
    setattr(request.state, name, default)

  return getattr(request.state, name)


def _last_user_text(chat: "ch.Chat") -> str:
  node = chat.match_one(role="user", index=-1)
  return (node.content or "").strip() if node else ""


def count_user_turns(chat: "ch.Chat") -> int:
  return len(chat.match(role="user"))


def is_substantive_message(text: str) -> bool:
  text = (text or "").strip()
  if not text or len(text) < 4:
    return False
  if SKIP_MESSAGE_RE.match(text):
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
  stored = _request_store("keel_task_brief", None)
  if stored is None:
    return None
  if isinstance(stored, TaskBrief):
    return stored
  return TaskBrief(**stored)


def store_brief(brief: TaskBrief) -> None:
  _request_store("keel_task_brief", brief.model_dump())


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


def inject_brief_marker(chat: "ch.Chat", brief: TaskBrief) -> None:
  if chat_has_brief_marker(chat):
    return

  met = get_met_criteria()
  chat.system(render_brief_marker(brief, met))
  logger.debug(f"{ID_PREFIX}: injected hidden brief marker into chat")


def should_inject_anchor(user_turns: int) -> bool:
  every = boost_config.KEEL_ANCHOR_EVERY.value
  if every < 1:
    every = 1
  return user_turns >= 2 and user_turns % every == 0


def get_met_criteria() -> set[int]:
  stored = _request_store("keel_met_criteria", [])
  return set(stored)


def store_met_criteria(indices: set[int]) -> None:
  _request_store("keel_met_criteria", sorted(indices))


def update_met_criteria_from_history(chat: "ch.Chat", brief: TaskBrief) -> set[int]:
  met = get_met_criteria()
  if not brief.acceptance_criteria:
    return met

  assistant_text = " ".join(
    (node.content or "")
    for node in chat.match(role="assistant")
  ).lower()

  for index, criterion in enumerate(brief.acceptance_criteria):
    if index in met:
      continue
    needle = criterion.strip().lower()
    if len(needle) >= 12 and needle in assistant_text:
      met.add(index)

  store_met_criteria(met)
  return met


def next_unmet_criterion(brief: TaskBrief, met: set[int]) -> str | None:
  for index, criterion in enumerate(brief.acceptance_criteria):
    if index not in met:
      return criterion
  return None


def render_anchor_block(brief: TaskBrief, next_criterion: str | None = None) -> str:
  constraints = brief.constraints or ["Stay within the stated scope."]
  lines = [
    "<task_anchor>",
    f"<objective>{brief.objective}</objective>",
    "<constraints>",
    *(f"- {item}" for item in constraints),
    "</constraints>",
  ]

  if next_criterion:
    lines.extend([
      "<next_criterion>",
      next_criterion,
      "</next_criterion>",
    ])

  if brief.in_scope_paths:
    lines.append("<in_scope_paths>")
    lines.extend(f"- {path}" for path in brief.in_scope_paths)
    lines.append("</in_scope_paths>")

  lines.append("</task_anchor>")
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

  if brief.in_scope_paths:
    lines.append("<in_scope_paths>")
    lines.extend(f"- {path}" for path in brief.in_scope_paths)
    lines.append("</in_scope_paths>")

  if drift_detected:
    lines.append(
      "<drift_warning>Scope expansion was detected earlier — confirm only in-scope work shipped.</drift_warning>"
    )

  lines.extend([
    "<reminder>Verify each acceptance criterion before finishing.</reminder>",
    "</landing_checklist>",
  ])
  return "\n".join(lines)


def needs_keel(chat: "ch.Chat") -> bool:
  if not boost_config.KEEL_ENABLED.value:
    return False
  if getattr(chat, "llm", None) and getattr(chat.llm, "module", None) == ID_PREFIX:
    return True
  return deliverable.is_coding_deliverable(chat)


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


async def extract_task_brief(
  chat: "ch.Chat",
  llm: "llm.LLM",
  message: str,
) -> TaskBrief:
  intermediate = _cheap_llm(llm)
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
    path = re.sub(r"^[\s`'\"(]+", "", match.group(0).strip()).rstrip("`'\"")
    if path and path not in seen:
      seen.add(path)
      paths.append(path)
  return paths


async def ensure_task_brief(
  chat: "ch.Chat",
  llm: "llm.LLM",
  message: str,
) -> TaskBrief | None:
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

  store_brief(brief)
  inject_brief_marker(chat, brief)
  logger.info(f"{ID_PREFIX}: stored task brief with {len(brief.acceptance_criteria)} criteria")
  return brief


def _register_finish_wrapper(brief: TaskBrief, drift_detected: bool) -> None:
  checklist = render_landing_checklist(brief, drift_detected=drift_detected)

  async def finish(answer: str) -> str:
    """
    Return the final answer when the model is done using tools.
    Keel prepends a landing checklist so the model verifies acceptance criteria.

    Args:
      answer (str): Final answer to provide to the user.
    """
    logger.info(f"{ID_PREFIX}: landing checklist on finish")
    return f"{checklist}\n\n{answer}"

  try:
    tools.registry.set_local_tool("finish", finish)
  except ValueError:
    logger.debug(f"{ID_PREFIX}: finish tool already registered, skipping wrapper")


async def apply(chat: "ch.Chat", llm: "llm.LLM", config: dict | None = None):
  message = _last_user_text(chat)
  if not message:
    logger.warning(f"{ID_PREFIX}: No user message found, passing through")
    return await workflow_mod.complete_or_defer(llm, config)

  brief = get_stored_brief() or hydrate_brief_from_chat(chat)

  if not needs_keel(chat) and brief is None:
    logger.debug(f"{ID_PREFIX}: Pass-through — not a coding deliverable turn")
    return await workflow_mod.complete_or_defer(llm, config)

  user_turns = count_user_turns(chat)
  drift_detected = False

  if brief is None and is_substantive_message(message):
    await llm.emit_status("Keel: extracting task brief...")
    brief = await ensure_task_brief(chat, llm, message)

  if brief is None:
    return await workflow_mod.complete_or_defer(llm, config)

  if user_turns >= 2:
    drift_detected = detect_drift(message, brief)
    if drift_detected:
      logger.warning(f"{ID_PREFIX}: scope drift detected on turn {user_turns}")
      chat.system(
        "<drift_warning>Stay within the anchored task scope. "
        "Confirm scope changes with the user before expanding work.</drift_warning>"
      )

    met = update_met_criteria_from_history(chat, brief)

    if should_inject_anchor(user_turns):
      next_criterion = next_unmet_criterion(brief, met)
      chat.system(render_anchor_block(brief, next_criterion))
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
    logger.info(f"{ID_PREFIX}: done signal detected, injecting landing checklist")
    chat.system(render_landing_checklist(brief, drift_detected=drift_detected))

  _register_finish_wrapper(brief, drift_detected)
  return await workflow_mod.complete_or_defer(llm, config)