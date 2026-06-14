"""Heuristics for detecting coding deliverable requests in Boost chats."""

import re

import chat as ch

CODE_BLOCK_RE = re.compile(r"```[\w.-]*\n", re.IGNORECASE)
FILE_PATH_RE = re.compile(
  r"(?:^|[\s`'\"(])(?:[\w.-]+/)+[\w.-]+\.(?:py|ts|tsx|js|jsx|go|rs|java|rb|php|cs|cpp|c|h|hpp|swift|kt|scala|sql|yaml|yml|toml|json|md|sh|bash|zsh|dockerfile|makefile)\b",
  re.IGNORECASE,
)
CODING_KEYWORD_RE = re.compile(
  r"\b(?:implement|refactor|rewrite|debug|fix(?:\s+the)?\s+(?:bug|error|issue|test)|"
  r"write\s+(?:a\s+)?(?:function|class|module|script|test|code)|"
  r"add\s+(?:a\s+)?(?:function|method|class|test|endpoint|route|handler)|"
  r"create\s+(?:a\s+)?(?:file|module|component|api|endpoint|script|test)|"
  r"update\s+(?:the\s+)?(?:code|file|function|class|module|implementation)|"
  r"patch|diff|pull\s+request|commit|merge\s+conflict|unit\s+test|integration\s+test|"
  r"type\s*error|lint(?:er)?\s+error|compile\s+error|stack\s*trace|"
  r"make\s+it\s+work|ship\s+this|code\s+review)\b",
  re.IGNORECASE,
)
CODING_ACTION_RE = re.compile(
  r"\b(?:"
  r"fix(?:\s+(?:this|the|my))?\b|debug|patch|refactor|rewrite|implement|"
  r"add\b|update\b|change\b|modify\b|create\b|write\b|remove\b|delete\b|"
  r"correct\b|repair\b|make\s+it\s+work|ship\s+this"
  r")\b",
  re.IGNORECASE,
)
EXPLAIN_INTENT_RE = re.compile(
  r"\b(?:"
  r"explain(?:\s+(?:this|the|how|what|why|me))?\b|"
  r"what\s+(?:is|are|does|do)\b|how\s+(?:does|do|is|are|can|should)\b|"
  r"walk\s+me\s+through|help\s+me\s+understand|"
  r"describe(?:\s+how)?\b|clarify\b|"
  r"tell\s+me\s+(?:about|how|what)\b|"
  r"can\s+you\s+explain\b|"
  r"why\s+(?:is|are|does|do)\b"
  r")\b",
  re.IGNORECASE,
)
PROBLEM_INDICATOR_RE = re.compile(
  r"\b(?:"
  r"broken|bug(?:gy)?|bugs?\b|error|fails?|failing|wrong|incorrect|"
  r"crash(?:es|ing)?|exception|regression|issue|doesn'?t\s+work|not\s+working"
  r")\b",
  re.IGNORECASE,
)
NON_CODING_RE = re.compile(
  r"\b(?:explain|what\s+is|how\s+does|summarize|summary|overview|compare|pros\s+and\s+cons|"
  r"brainstorm|ideate|write\s+(?:a\s+)?(?:email|essay|poem|story|blog|article|tweet)|"
  r"translate|define|describe)\b",
  re.IGNORECASE,
)
RESEARCH_SIGNAL_RE = re.compile(
  r"\b(?:"
  r"latest|current|today|recent(?:ly)?|20\d{2}|version|release|changelog|release\s+notes?|"
  r"documentat(?:ion|e)|api\s+(?:reference|docs?|endpoint|behavior|spec|version)|"
  r"endpoint\s+(?:response|format|behavior)|breaking\s+changes?|migrate|migration|migrating|"
  r"upgrade(?:\s+path|\s+guide)?|compatib(?:le|ility)|deprecat(?:e|ed|ion)|"
  r"compare|versus|vs\.?|benchmark|pricing|availability|error\s+code|stack\s*overflow|"
  r"lookup|search\s+for|from\s+v?\d|to\s+v?\d|v\d+(?:\.\d+)+|semver"
  r")\b",
  re.IGNORECASE,
)
SKIP_MESSAGE_RE = re.compile(
  r"^\s*(?:"
  r"thanks?(?:\s+you)?|thank\s+you|thx|ok(?:ay)?|cool|great|perfect|sounds?\s+good|"
  r"got\s+it|understood|yes|no|yep|nope|sure|continue|go\s+on|go\s+ahead|"
  r"proceed|keep\s+going|lgtm|looks?\s+good|done|next|ship\s+it"
  r")\s*[.!]?\s*$",
  re.IGNORECASE,
)
ACK_PHRASE_RE = re.compile(
  r"^\s*(?:"
  r"(?:thanks?(?:\s+(?:a\s+lot|so\s+much|for\b.*)?)?|thank\s+you(?:\s+so\s+much)?|thx)|"
  r"(?:ok(?:ay)?|cool|great|perfect|nice|awesome|sweet)|"
  r"sounds?\s+good|got\s+it|understood|makes\s+sense|"
  r"(?:yes|no|yep|nope|sure|yup)|"
  r"(?:looks?\s+good|that\s+works|that(?:'s| is)\s+(?:good|great|perfect|fine))|"
  r"(?:continue|go\s+on|go\s+ahead|proceed|keep\s+going|lgtm|done|next|ship\s+it)"
  r")\b",
  re.IGNORECASE,
)
PRIOR_CODE_ACTION_RE = re.compile(
  r"\b(?:fix|implement|refactor|add|update|patch|debug|change|modify|create|write)\b",
  re.IGNORECASE,
)

MAX_ACKNOWLEDGMENT_CHARS = 120
MAX_SHORT_ACK_CHARS = 80


def _last_user_text(chat: "ch.Chat") -> str:
  node = chat.match_one(role="user", index=-1)
  return (node.content or "") if node else ""


def has_explain_intent(text: str) -> bool:
  """Return True when the user is asking for understanding rather than edits."""
  return bool(EXPLAIN_INTENT_RE.search(text or ""))


def has_coding_action_intent(text: str) -> bool:
  """Return True when the user is asking for concrete code changes."""
  text = text or ""
  return bool(CODING_ACTION_RE.search(text) or CODING_KEYWORD_RE.search(text))


def has_problem_indicator(text: str) -> bool:
  """Return True when the user describes broken or failing code without saying 'fix'."""
  return bool(PROBLEM_INDICATOR_RE.search(text or ""))


def has_research_signals(text: str) -> bool:
  """
  Return True when the message likely needs live docs, version facts, or lookups.

  Shared by research modules (caveman, ponytail) to avoid firing on pure
  implementation edits that do not need external facts.
  """
  text = (text or "").strip()
  if not text:
    return False
  if "?" in text:
    return True
  if re.search(r"https?://", text, re.IGNORECASE):
    return True
  return bool(RESEARCH_SIGNAL_RE.search(text))


def is_acknowledgment(text: str) -> bool:
  """
  Return True for short gratitude, approval, or continuation messages.

  Handles borderline forms like ``thanks for the help`` and ``looks good, thanks``
  while rejecting ``ok, but fix the timeout next``.
  """
  text = (text or "").strip()
  if not text:
    return False
  if SKIP_MESSAGE_RE.match(text):
    return True
  if len(text) > MAX_ACKNOWLEDGMENT_CHARS:
    return False
  if not ACK_PHRASE_RE.search(text):
    return False
  if has_coding_action_intent(text) or has_explain_intent(text):
    return False
  if len(text) <= MAX_SHORT_ACK_CHARS:
    return True
  if re.search(r"\b(?:thanks?|thx|thank\s+you)\b", text, re.IGNORECASE):
    return True
  return False


def _wants_code_changes(text: str) -> bool:
  """Return True when the message asks for edits, not just context."""
  if has_coding_action_intent(text):
    return True
  if has_problem_indicator(text) and not has_explain_intent(text):
    return True
  return bool(PRIOR_CODE_ACTION_RE.search(text))


def deliverable_signals(text: str, *, has_prior_code_block: bool = False) -> list[str]:
  """
  Return active deliverable signal names for the latest user text.

  Used by selective modules (e.g. autocheck) that require multiple signals
  before running expensive post-processing.
  """
  text = (text or "").strip()
  signals: list[str] = []

  if not text or is_acknowledgment(text):
    return signals

  has_code_block = bool(CODE_BLOCK_RE.search(text))
  has_file_path = bool(FILE_PATH_RE.search(text))
  has_coding_keyword = bool(CODING_KEYWORD_RE.search(text))
  wants_changes = _wants_code_changes(text)

  if has_explain_intent(text) and not wants_changes:
    return signals

  if has_research_signals(text) and not wants_changes and not has_code_block and not has_file_path:
    return signals

  if has_code_block:
    if wants_changes:
      signals.append("code_block")
  if has_file_path:
    if wants_changes:
      signals.append("file_path")
  if has_coding_keyword:
    signals.append("coding_keyword")
  if has_prior_code_block and PRIOR_CODE_ACTION_RE.search(text):
    signals.append("prior_code_block")

  return signals


def count_deliverable_signals(chat: "ch.Chat") -> int:
  """Count how many deliverable signals the latest user turn carries."""
  text = _last_user_text(chat)
  return len(deliverable_signals(text, has_prior_code_block=chat.has_substring("```")))


def is_coding_deliverable(chat: "ch.Chat") -> bool:
  """
  Heuristic gate for agentic coding modules.

  Returns True when the latest user message likely expects code, patches,
  or repo-grounded implementation work rather than a purely explanatory answer.
  """
  text = _last_user_text(chat).strip()
  if not text:
    return False

  if is_acknowledgment(text):
    return False

  has_code_block = bool(CODE_BLOCK_RE.search(text))
  has_file_path = bool(FILE_PATH_RE.search(text))
  has_coding_keyword = bool(CODING_KEYWORD_RE.search(text))
  wants_changes = _wants_code_changes(text)

  if has_explain_intent(text) and not wants_changes:
    return False

  if has_research_signals(text) and not wants_changes and not has_code_block and not has_file_path:
    return False

  looks_explanatory = (
    bool(NON_CODING_RE.search(text))
    and not has_code_block
    and not has_file_path
    and not wants_changes
  )
  if looks_explanatory and not has_coding_keyword:
    return False

  if has_code_block or has_file_path:
    return wants_changes

  if has_coding_keyword or wants_changes:
    return True

  if chat.has_substring("```") and PRIOR_CODE_ACTION_RE.search(text):
    return True

  return False