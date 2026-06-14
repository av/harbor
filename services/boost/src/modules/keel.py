"""Task anchor for multi-turn coding sessions in Harbor Boost."""

import re
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

import chat as ch
import config
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

On later turns (turn >= 2) it injects a compact `<task_anchor>` system block with
the objective, constraints, and the next unmet acceptance criterion. Simple drift
heuristics flag scope-expansion phrases. A landing checklist is injected when the
user signals completion or when the model calls the `finish` tool.

**When to use**

- Multi-turn agentic coding where the model may drift from the original objective
- Long-running tasks with acceptance criteria and in-scope path constraints
- First substantive coding message extracts and stores a `TaskBrief`; later turns
  receive a compact `<task_anchor>` reminder

This is a minimal stub — not a full drift guard. Pair with `autocheck` for
deliverable verification or `diffscope` for file-scope enforcement.

**Parameters**

- `enabled` — when false, pass through without anchoring. Default: `true`

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

DONE_SIGNAL_RE = re.compile(
  r"\b(?:"
  r"done|finished|finish\s+up|ship\s+it|ready\s+to\s+ship|that(?:'s| is)\s+all|"
  r"we(?:'re| are)\s+done|good\s+to\s+go|complete(?:d)?|wrap\s+up|call\s+it\s+done"
  r")\b",
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
  return bool(DONE_SIGNAL_RE.search((text or "").strip()))


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
        path = re.sub(r"^[\s`'\"(]+", "", raw.strip()).rstrip("`'\"").lower()
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
  lines = [
    "<landing_checklist>",
    f"<objective>{brief.objective}</objective>",
    "<acceptance_criteria>",
  ]

  met = get_met_criteria()
  for index, criterion in enumerate(brief.acceptance_criteria or ["Task completed as requested."]):
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
  if not config.KEEL_ENABLED.value:
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

  if not needs_keel(chat) and not get_stored_brief():
    logger.debug(f"{ID_PREFIX}: Pass-through — not a coding deliverable turn")
    return await workflow_mod.complete_or_defer(llm, config)

  user_turns = count_user_turns(chat)
  drift_detected = False

  brief = get_stored_brief()
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
    next_criterion = next_unmet_criterion(brief, met)
    chat.system(render_anchor_block(brief, next_criterion))
    logger.debug(
      f"{ID_PREFIX}: injected anchor on turn {user_turns}"
      + (f", next criterion: {next_criterion[:60]}" if next_criterion else ", all criteria met")
    )

  if is_done_signal(message):
    logger.info(f"{ID_PREFIX}: done signal detected, injecting landing checklist")
    chat.system(render_landing_checklist(brief, drift_detected=drift_detected))

  _register_finish_wrapper(brief, drift_detected)
  return await workflow_mod.complete_or_defer(llm, config)