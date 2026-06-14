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
NON_CODING_RE = re.compile(
  r"\b(?:explain|what\s+is|how\s+does|summarize|summary|overview|compare|pros\s+and\s+cons|"
  r"brainstorm|ideate|write\s+(?:a\s+)?(?:email|essay|poem|story|blog|article|tweet)|"
  r"translate|define|describe)\b",
  re.IGNORECASE,
)


def _last_user_text(chat: "ch.Chat") -> str:
  node = chat.match_one(role="user", index=-1)
  return (node.content or "") if node else ""


def deliverable_signals(text: str, *, has_prior_code_block: bool = False) -> list[str]:
  """
  Return active deliverable signal names for the latest user text.

  Used by selective modules (e.g. autocheck) that require multiple signals
  before running expensive post-processing.
  """
  text = (text or "").strip()
  signals: list[str] = []

  if CODE_BLOCK_RE.search(text):
    signals.append("code_block")
  if FILE_PATH_RE.search(text):
    signals.append("file_path")
  if CODING_KEYWORD_RE.search(text):
    signals.append("coding_keyword")
  if has_prior_code_block and any(
    marker in text.lower()
    for marker in ("fix", "implement", "refactor", "add", "update", "patch")
  ):
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

  has_code_block = bool(CODE_BLOCK_RE.search(text))
  has_file_path = bool(FILE_PATH_RE.search(text))
  has_coding_keyword = bool(CODING_KEYWORD_RE.search(text))
  looks_explanatory = bool(NON_CODING_RE.search(text)) and not has_code_block and not has_file_path

  if looks_explanatory and not has_coding_keyword:
    return False

  if has_code_block or has_file_path:
    return True

  if has_coding_keyword:
    return True

  if chat.has_substring("```") and any(
    marker in text.lower()
    for marker in ("fix", "implement", "refactor", "add", "update", "patch")
  ):
    return True

  return False