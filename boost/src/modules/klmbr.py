# klmbr - Kalambur
# https://github.com/av/klmbr

import random

from chat import Chat
from config import HARBOR_BOOST_KLMBR_MODS, HARBOR_BOOST_KLMBR_PERCENTAGE, HARBOR_BOOST_KLMBR_STRAT, HARBOR_BOOST_KLMBR_STRAT_PARAMS
from selection import apply_selection_strategy

import log
import llm

logger = log.setup_logger(__name__)

ID_PREFIX = "klmbr"

leetspeak_map = {
  "a": "4",
  "e": "3",
  "i": "1",
  "o": "0",
  "s": "5",
  "t": "7",
  "b": "8",
  "g": "9",
  "l": "1",
}

diacritics = ["̀", "́", "̂", "̃", "̈", "̄", "̆", "̇", "̊", "̋"]

punctuation = ".,!?;:"


def capitalize(chars, idx):
  return chars[idx].swapcase()


def diacritic(chars, idx):
  if chars[idx].isalpha():
    return chars[idx] + random.choice(diacritics)
  return chars[idx]


def leetspeak(chars, idx):
  return leetspeak_map.get(chars[idx].lower(), chars[idx])


def remove_vowel(chars, idx):
  if chars[idx].lower() in "aeiou":
    return ""
  return chars[idx]


mods = {
  "capitalize": capitalize,
  "diacritic": diacritic,
  "leetspeak": leetspeak,
  "remove_vowel": remove_vowel,
}


def modify_text(**kwargs):
  text = kwargs.get("text", "")
  percentage = kwargs.get("percentage", 0)
  target_mods = kwargs.get("mods")

  if target_mods[0] == "all":
    target_mods = list(mods.keys())

  if not text:
    return "", {}

  if not 0 <= percentage <= 100:
    raise ValueError("Percentage must be between 0 and 100")

  words = text.split()
  chars = list(text)
  num_chars_to_modify = max(1, int(len(chars) * (percentage / 100)))
  indices_to_modify = random.sample(range(len(chars)), num_chars_to_modify)
  word_mapping = {}

  for idx in indices_to_modify:
    modification = random.choice(target_mods)

    current_length = 0
    for word_idx, word in enumerate(words):
      if current_length <= idx < current_length + len(word):
        original_word = word
        word_start_idx = current_length
        break
      current_length += len(word) + 1
    else:
      continue

    chars[idx] = mods[modification](chars, idx)
    modified_word = "".join(
      chars[word_start_idx:word_start_idx + len(original_word)]
    )

    if modified_word != original_word:
      cleaned_modified_word = modified_word.rstrip(punctuation)
      cleaned_original_word = original_word.rstrip(punctuation)
      word_mapping[cleaned_modified_word] = cleaned_original_word

  modified_text = "".join(chars)
  return modified_text, word_mapping


async def apply(chat: Chat, llm: 'llm.LLM'):
  strat = HARBOR_BOOST_KLMBR_STRAT.value
  strat_params = HARBOR_BOOST_KLMBR_STRAT_PARAMS.value
  percentage = HARBOR_BOOST_KLMBR_PERCENTAGE.value
  mods = HARBOR_BOOST_KLMBR_MODS.value
  debug_info = {
    "strat": strat,
    "strat_params": strat_params,
    "percentage": percentage,
    "mods": mods,
  }

  logger.debug(f"klmbr: {debug_info}")

  nodes = apply_selection_strategy(chat, strategy=strat, params=strat_params)

  for node in nodes:
    content, mapping = modify_text(
      text=node.content, percentage=percentage, mods=mods
    )
    node.content = content
    node.meta["klmbr"] = mapping

  return llm.stream_chat_completion(chat=chat)
