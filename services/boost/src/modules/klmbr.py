# klmbr - Kalambur
# https://github.com/av/klmbr

import random

from config import KLMBR_MODS, KLMBR_PERCENTAGE, KLMBR_STRAT, KLMBR_STRAT_PARAMS

import log
import llm
import chat as ch
import selection

logger = log.setup_logger(__name__)

ID_PREFIX = "klmbr"
DOCS = """
![klmbr screenshot](https://github.com/av/klmbr/raw/main/assets/c4ndl3.png)
![klmbr screenshot](./boost-klmbr.png)

Boosts model creativity by applying character-level random rewrites to the input. Read a full overview of the technique in the [source repo](https://github.com/av/klmbr).

Every LLM will respond to rewrites in a different way. Some models will generate more diverse completions, while others might start generating completely random sequences. Default parameters are tuned for Llama 3.1 8B, you might want to adjust them when running with a different model.

**Parameters**

- `percentage` - amount of characters to rewrite in the input. Default is `35`
- `mods` - types of rewrites to apply. Default is `all`, available options:
  - `capitalize` - swaps character capitalization
  - `diacritic` - adds a random diacritic to the character
  - `leetspeak` - replaces characters with leetspeak equivalents
  - `remove_vowel` - removes vowels from the input
  - `invert_180` - inverts characters 180 degrees
  - `unicode_lookalike` - replaces characters with Unicode lookalikes from other scripts
  - `homoglyph` - replaces characters with visually identical homoglyphs
  - `zero_width` - inserts zero-width characters after the character
  - `zalgo` - adds multiple combining marks to create zalgo text effect
- `strat` - strategy for selection of the messages to rewrite. Default is `match`
  - `all` - match all messages
  - `first` - match first message regardless of the role
  - `last` - match last message regardless of the role
  - `any` - match one random message
  - `percentage` - match a percentage of random messages from the conversation
  - `user` - match all user messages
  - `match` - use a filter to match messages
- `strat_params` - parameters (filter) for the selection strategy. Default matches all user messages
  - `percentage` - for `percentage` strat - the percentage of messages to match, default is `50`
  - `index` - for `match` strat - the index of the message to match
  - `role` - for `match` strat - the role of the message to match
  - `substring` - for `match` strat - will match messages containing the substring

**Examples**

```bash
# Reduce the rewrite percentage
harbor boost klmbr percentage 20

# Enable/disable rewrite modules
harbor boost klmbr mods rm all
harbor boost klmbr mods add capitalize
harbor boost klmbr mods add diacritic
harbor boost klmbr mods add leetspeak
harbor boost klmbr mods add remove_vowel
harbor boost klmbr mods add invert_180
harbor boost klmbr mods add unicode_lookalike
harbor boost klmbr mods add homoglyph
harbor boost klmbr mods add zero_width
harbor boost klmbr mods add zalgo

# Change the selection strategy
# 1. Match all user messages
harbor boost klmbr strat match
harbor boost klmbr strat_params role user
# 2. Match the last message (regardless of the role)
harbor boost klmbr strat match
harbor boost klmbr strat_params index -1
# 3. Match messages containing a substring
harbor boost klmbr strat match
harbor boost klmbr strat_params substring "random"
```

"""

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

invert_map = {
  'a': 'ɐ',
  'b': 'q',
  'c': 'ɔ',
  'd': 'p',
  'e': 'ǝ',
  'f': 'ɟ',
  'g': 'ƃ',
  'h': 'ɥ',
  'i': 'ᴉ',
  'j': 'ɾ',
  'k': 'ʞ',
  'l': 'l',
  'n': 'u',
  'o': 'o',
  'p': 'd',
  'q': 'b',
  'r': 'ɹ',
  's': 's',
  't': 'ʇ',
  'u': 'n',
  'v': 'ʌ',
  'w': 'ʍ',
  'x': 'x',
  'y': 'ʎ',
  'z': 'z',
  'A': '∀',
  'B': '𐐒',
  'C': 'Ɔ',
  'D': 'ᗡ',
  'E': 'Ǝ',
  'F': 'Ⅎ',
  'G': '⅁',
  'H': 'H',
  'I': 'I',
  'K': '⋊',
  'L': '˥',
  'M': 'W',
  'N': 'N',
  'O': 'O',
  'P': 'Ԁ',
  'Q': 'Q',
  'R': 'ᴚ',
  'S': 'S',
  'T': '⊥',
  'U': '∩',
  'V': 'Λ',
  'W': 'M',
  'X': 'X',
  'Y': '⅄',
  'Z': 'Z',
}

diacritics = ["̀", "́", "̂", "̃", "̈", "̄", "̆", "̇", "̊", "̋"]

unicode_lookalike_map = {
  'a': 'а',  # Cyrillic
  'c': 'с',  # Cyrillic
  'e': 'е',  # Cyrillic
  'o': 'ο',  # Greek omicron
  'p': 'р',  # Cyrillic
  'x': 'х',  # Cyrillic
  'y': 'у',  # Cyrillic
  'A': 'А',  # Cyrillic
  'B': 'В',  # Cyrillic
  'C': 'С',  # Cyrillic
  'E': 'Ε',  # Greek
  'H': 'Η',  # Greek
  'I': 'Ι',  # Greek
  'K': 'Κ',  # Greek
  'M': 'Μ',  # Greek
  'N': 'Ν',  # Greek
  'O': 'Ο',  # Greek
  'P': 'Ρ',  # Greek
  'T': 'Τ',  # Greek
  'X': 'Χ',  # Greek
  'Y': 'Υ',  # Greek
  'Z': 'Ζ',  # Greek
}

homoglyph_map = {
  'a': 'а',  # Cyrillic a
  'e': 'е',  # Cyrillic e
  'o': 'о',  # Cyrillic o
  'p': 'р',  # Cyrillic r
  'c': 'с',  # Cyrillic s
  'y': 'у',  # Cyrillic u
  'x': 'х',  # Cyrillic h
  'i': 'і',  # Cyrillic i
  'j': 'ј',  # Cyrillic j
  's': 'ѕ',  # Cyrillic dze
  'A': 'А',  # Cyrillic A
  'B': 'В',  # Cyrillic V
  'C': 'С',  # Cyrillic S
  'E': 'Е',  # Cyrillic E
  'H': 'Н',  # Cyrillic N
  'I': 'І',  # Cyrillic I
  'J': 'Ј',  # Cyrillic J
  'K': 'К',  # Cyrillic K
  'M': 'М',  # Cyrillic M
  'O': 'О',  # Cyrillic O
  'P': 'Р',  # Cyrillic P
  'S': 'Ѕ',  # Cyrillic S
  'T': 'Т',  # Cyrillic T
  'X': 'Х',  # Cyrillic Kh
  'Y': 'Υ',  # Greek Upsilon
}

zero_width_chars = [
  '\u200B',  # Zero Width Space
  '\u200C',  # Zero Width Non-Joiner
  '\u200D',  # Zero Width Joiner
  '\uFEFF',  # Zero Width No-Break Space
]

zalgo_marks = [
  # Combining marks above
  '\u0300', '\u0301', '\u0302', '\u0303', '\u0304', '\u0305', '\u0306',
  '\u0307', '\u0308', '\u0309', '\u030A', '\u030B', '\u030C', '\u030D',
  '\u030E', '\u030F', '\u0310', '\u0311', '\u0312', '\u0313', '\u0314',
  '\u0315', '\u031A', '\u031B', '\u033D', '\u033E', '\u033F', '\u0340',
  '\u0341', '\u0342', '\u0343', '\u0344', '\u0346',
  # Combining marks below
  '\u0316', '\u0317', '\u0318', '\u0319', '\u031C', '\u031D', '\u031E',
  '\u031F', '\u0320', '\u0321', '\u0322', '\u0323', '\u0324', '\u0325',
  '\u0326', '\u0327', '\u0328', '\u0329', '\u032A', '\u032B', '\u032C',
  '\u032D', '\u032E', '\u032F', '\u0330', '\u0331', '\u0332', '\u0333',
  '\u0339', '\u033A', '\u033B', '\u033C', '\u0345', '\u0347', '\u0348',
  '\u0349', '\u034D', '\u034E',
  # Combining marks through
  '\u0335', '\u0336', '\u0337', '\u0338',
]

punctuation = ".,!?;:"


def capitalize(chars, idx):
  return chars[idx].swapcase()


def diacritic(chars, idx):
  if chars[idx].isalpha():
    return chars[idx] + random.choice(diacritics)
  return chars[idx]


def is_standalone_vowel(chars, idx):
    if not chars or idx < 0 or idx >= len(chars):
        return False

    vowels = 'aeiouAEIOU'
    if chars[idx] not in vowels:
        return False

    prev_is_space = idx == 0 or chars[idx-1].isspace()
    next_is_space = idx == len(chars)-1 or chars[idx+1].isspace()

    return prev_is_space or next_is_space


def leetspeak(chars, idx):
  if is_standalone_vowel(chars, idx):
    return chars[idx]

  return leetspeak_map.get(chars[idx].lower(), chars[idx])

def remove_vowel(chars, idx):
  if not is_standalone_vowel(chars, idx) and chars[idx].lower() in "aeiou":
    return ""

  return chars[idx]


def invert_180(chars, idx):
  if is_standalone_vowel(chars, idx):
    return chars[idx]

  return invert_map.get(chars[idx], chars[idx])


def unicode_lookalike(chars, idx):
  if is_standalone_vowel(chars, idx):
    return chars[idx]

  return unicode_lookalike_map.get(chars[idx], chars[idx])


def homoglyph(chars, idx):
  if is_standalone_vowel(chars, idx):
    return chars[idx]

  return homoglyph_map.get(chars[idx], chars[idx])


def zero_width(chars, idx):
  return chars[idx] + random.choice(zero_width_chars)


def zalgo(chars, idx):
  if chars[idx].isalpha():
    num_marks = random.randint(1, 3)
    marks = ''.join(random.choice(zalgo_marks) for _ in range(num_marks))
    return chars[idx] + marks
  return chars[idx]


mods = {
  "capitalize": capitalize,
  "diacritic": diacritic,
  "leetspeak": leetspeak,
  "remove_vowel": remove_vowel,
  "invert_180": invert_180,
  "unicode_lookalike": unicode_lookalike,
  "homoglyph": homoglyph,
  "zero_width": zero_width,
  "zalgo": zalgo,
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


async def apply(chat: 'ch.Chat', llm: 'llm.LLM'):
  strat = KLMBR_STRAT.value
  strat_params = KLMBR_STRAT_PARAMS.value
  percentage = KLMBR_PERCENTAGE.value
  mods = KLMBR_MODS.value
  debug_info = {
    "strat": strat,
    "strat_params": strat_params,
    "percentage": percentage,
    "mods": mods,
  }

  logger.debug(f"{ID_PREFIX}: {debug_info}")

  nodes = selection.apply_strategy(chat, strategy=strat, params=strat_params)

  for node in nodes:
    content, mapping = modify_text(
      text=node.content, percentage=percentage, mods=mods
    )
    node.content = content
    node.meta[ID_PREFIX] = mapping

  await llm.emit_status(llm.chat.tail.content)
  await llm.stream_final_completion(chat=chat)

if __name__ == "__main__":
  sample = "Which company created Hacker News?"

  print("Original:", sample)
  print()

  # Test with all mods
  modified, mapping = modify_text(text=sample, percentage=30, mods=[
    "all",
    # "diacritic",
    # "remove_vowel",
    # "invert_180",
    # "unicode_lookalike",
    # "homoglyph",
    # "zero_width",
    # "zalgo",
  ])
  double_modified, _ = modify_text(
    text=modified, percentage=30, mods=["all"]
  )
  print()
  print("All mods (100%):", modified)
  print("Double modified:", double_modified)