"""Shared helpers for terse/YAGNI style Boost modules (caveman, ponytail)."""

import re
from typing import TYPE_CHECKING

import research.workflow as workflow_mod

if TYPE_CHECKING:
  import chat as ch

LEVEL_ALIASES = {
  "lite": "lite",
  "full": "full",
  "ultra": "ultra",
  "off": "off",
  "wenyan-lite": "wenyan-lite",
  "wenyan-full": "wenyan-full",
  "wenyan-ultra": "wenyan-ultra",
}

STOP_RE = re.compile(
  r"\b(?:stop\s+(?:caveman|ponytail)|normal\s+mode)\b",
  re.IGNORECASE,
)

LEVEL_COMMAND_RE = re.compile(
  r"/(?:caveman|ponytail)\s+(lite|full|ultra|off|wenyan-lite|wenyan-full|wenyan-ultra)\b",
  re.IGNORECASE,
)


def normalize_level(level: str | None, *, default: str = "full") -> str:
  value = (level or default).strip().lower()
  return LEVEL_ALIASES.get(value, default)


def level_from_user_text(text: str) -> str | None:
  match = LEVEL_COMMAND_RE.search(text or "")
  if not match:
    return None
  return normalize_level(match.group(1))


def style_disabled_by_user(text: str) -> bool:
  return bool(STOP_RE.search(text or ""))


def resolve_style_level(
  chat: "ch.Chat",
  *,
  default: str,
  config_level: str | None = None,
) -> str:
  from research.orchestrate import last_user_text

  text = last_user_text(chat)
  if style_disabled_by_user(text):
    return "off"

  command_level = level_from_user_text(text)
  if command_level:
    return command_level

  if config_level:
    return normalize_level(config_level, default=default)

  return normalize_level(default)


def intensity_block(module: str, level: str) -> str:
  if module == "caveman":
    if level == "lite":
      return (
        "Intensity lite: no filler or hedging; keep articles and full sentences; "
        "professional but tight."
      )
    if level == "ultra":
      return (
        "Intensity ultra: abbreviate prose words only (DB/auth/config/req/res/fn/impl); "
        "use arrows for causality; never abbreviate code symbols, API names, or error strings."
      )
    if level.startswith("wenyan"):
      return f"Intensity {level}: classical Chinese compression per caveman wenyan rules."
    return (
      "Intensity full: drop articles; fragments OK; short synonyms; classic caveman style. "
      "No tool-call narration, no decorative tables/emoji, no long raw error-log dumps "
      "unless asked. Standard acronyms OK; no invented abbreviations."
    )

  if level == "lite":
    return (
      "Intensity lite: build what was asked, but name the lazier alternative in one line."
    )
  if level == "ultra":
    return (
      "Intensity ultra: YAGNI extremist; deletion before addition; ship the one-liner and "
      "challenge the rest of the requirement."
    )
  return (
    "Intensity full: enforce the ladder; stdlib and native features first; shortest diff wins."
  )


async def apply_style_and_continue(
  chat: "ch.Chat",
  llm,
  config: dict | None,
  *,
  module_id: str,
  prompt: str,
  level: str,
) -> None:
  if level == "off":
    return await workflow_mod.complete_or_defer(llm, config)

  block = (
    f"<{module_id}_style active=\"true\" level=\"{level}\">\n"
    f"{prompt.strip()}\n\n"
    f"{intensity_block(module_id, level)}\n"
    f"</{module_id}_style>"
  )
  root = chat.root()
  if root.role == "system" and isinstance(root.content, str):
    root.content = f"{block}\n\n{root.content}"
  elif root.role == "system" and isinstance(root.content, list):
    root.content = [{"type": "text", "text": block}, *root.content]
  else:
    chat.system(block)
  return await workflow_mod.complete_or_defer(llm, config)
