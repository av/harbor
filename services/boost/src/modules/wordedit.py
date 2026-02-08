import asyncio
import os
import uuid
from dataclasses import dataclass, field

import log
import chat as ch
import llm
import tools.registry

ID_PREFIX = 'wordedit'
DOCS = """
LLM composes its response through word-level tool calls instead of streaming.

The model builds a response word-by-word using CRUD operations, allowing it to iterate and refine before delivering the final result.

The visual artifact UI is compatible with Open WebUI and shows real-time word buffer updates.

```bash
# with Harbor
harbor boost modules add wordedit

# Standalone usage
docker run \\
  -e "HARBOR_BOOST_OPENAI_URLS=http://172.17.0.1:11434/v1" \\
  -e "HARBOR_BOOST_OPENAI_KEYS=sk-ollama" \\
  -e "HARBOR_BOOST_MODULES=wordedit" \\
  -p 8004:8000 \\
  ghcr.io/av/harbor-boost:latest
```
"""

logger = log.setup_logger(ID_PREFIX)

current_dir = os.path.dirname(os.path.abspath(__file__))
artifact_path = os.path.join(
  current_dir, '..', 'custom_modules', 'artifacts', 'wordedit_mini.html'
)


async def serve_artifact(llm: 'llm.LLM'):
  with open(artifact_path, 'r') as f:
    artifact = f.read()
  await llm.emit_artifact(artifact)
  await asyncio.sleep(0.5)


@dataclass
class Word:
  text: str
  id: str = field(default_factory=lambda: str(uuid.uuid4())[:6])


class Words:
  def __init__(self):
    self.words: list[Word] = []

  def render(self) -> str:
    return '\n'.join(f'[{w.id}] {w.text}' for w in self.words)

  def to_text(self) -> str:
    return ' '.join(w.text for w in self.words)

  def get_index(self, id: str) -> int:
    for i, w in enumerate(self.words):
      if w.id == id:
        return i
    return -1

  def add(self, text: str) -> Word:
    w = Word(text=text)
    self.words.append(w)
    return w

  def insert_before(self, id: str, text: str) -> Word | None:
    idx = self.get_index(id)
    if idx == -1:
      return None
    w = Word(text=text)
    self.words.insert(idx, w)
    return w

  def insert_after(self, id: str, text: str) -> Word | None:
    idx = self.get_index(id)
    if idx == -1:
      return None
    w = Word(text=text)
    self.words.insert(idx + 1, w)
    return w

  def update(self, id: str, text: str) -> bool:
    idx = self.get_index(id)
    if idx == -1:
      return False
    self.words[idx].text = text
    return True

  def delete(self, id: str) -> bool:
    idx = self.get_index(id)
    if idx == -1:
      return False
    self.words.pop(idx)
    return True


SYSTEM_PROMPT = """
# CRITICAL: WORD EDIT MODE ACTIVE

You are NOT operating normally. Your text output is COMPLETELY DISCARDED. The user will NEVER see anything you write as text.

## THE ONLY WAY TO RESPOND TO THE USER IS BY CALLING TOOLS

This is not optional. This is not a suggestion. If you write text without calling tools, the user receives NOTHING.

---

## HOW THIS SYSTEM WORKS

1. You have a "response buffer" - a list of words that will become your final answer
2. The buffer starts EMPTY: {buffer}
3. You BUILD your response by calling `add_word` repeatedly
4. Each tool call returns the updated buffer state so you can see your progress
5. When you STOP (no more tool calls), the buffer is joined with spaces and sent to the user

### WHAT THE USER SEES vs WHAT YOU SEE

| You produce | User sees |
|-------------|-----------|
| Text/thinking | NOTHING (discarded) |
| Tool calls | The accumulated buffer content |

---

## YOUR TOOLS

### `add_word(text)` - MOST IMPORTANT
Appends a word or short phrase (1-4 words) to the END of the buffer.
- Call this repeatedly to build your response
- Example: add_word("Hello,") → add_word("how are") → add_word("you?")
- Result buffer: "Hello, how are you?"

### `insert_before(id, text)`
Insert text BEFORE an existing word (identified by its ID from the buffer).

### `insert_after(id, text)`
Insert text AFTER an existing word.

### `update_word(id, text)`
Replace the text of an existing word.

### `delete_word(id)`
Remove a word from the buffer.

---

## STEP-BY-STEP INSTRUCTIONS

1. **READ** the user's message below
2. **PLAN** your response mentally (this text is hidden from user)
3. **BUILD** your response by calling `add_word` for each part:
   - Start with the first word/phrase
   - Continue adding until your response is complete
4. **REVIEW** the buffer state after each call
5. **EDIT** if needed using update/delete/insert tools
6. **STOP** when satisfied - stopping sends the buffer to the user

---

## EXAMPLE SESSION

User asks: "What is 2+2?"

You should call:
1. `add_word("The")` → Buffer: [a1b2c3] The
2. `add_word("answer is")` → Buffer: [a1b2c3] The, [d4e5f6] answer is
3. `add_word("4.")` → Buffer: [a1b2c3] The, [d4e5f6] answer is, [g7h8i9] 4.

Then STOP. User receives: "The answer is 4."

---

## COMMON MISTAKES TO AVOID

❌ Writing a text response and expecting user to see it → THEY WON'T
❌ Explaining what you're doing instead of using tools → USER SEES NOTHING
❌ Calling tools without text parameter → INVALID
❌ Forgetting to call add_word at all → USER GETS EMPTY RESPONSE

✅ Call add_word for EVERY part of your intended response
✅ Use short phrases (1-4 words) per call for granularity
✅ Review buffer state, make edits if needed
✅ Stop when the buffer contains your complete response

---

## CURRENT BUFFER STATE

{buffer}

---

## BEGIN NOW

Read the user's message. Respond ONLY by calling tools. Your text is invisible. START with add_word calls immediately.
"""


async def apply(chat: 'ch.Chat', llm: 'llm.LLM'):
  await serve_artifact(llm)
  await llm.emit_listener_event('wordedit.status', {'status': 'Initializing buffer'})

  words = Words()

  async def add_word(text: str) -> str:
    """
    Append a word or short phrase to the end of the response buffer.

    Args:
      text (str): The word or short phrase to add (1-4 words recommended)
    """
    w = words.add(text)
    await llm.emit_status(f"+ {w.text}")
    await llm.emit_listener_event('wordedit.word.add', {'id': w.id, 'text': w.text})
    return f"Added [{w.id}] '{w.text}'\n\nCurrent buffer:\n{words.render()}"

  async def insert_before(id: str, text: str) -> str:
    """
    Insert a word or phrase before the word with the given ID.

    Args:
      id (str): The ID of the word to insert before
      text (str): The word or short phrase to insert
    """
    w = words.insert_before(id, text)
    if w is None:
      return f"Error: ID '{id}' not found"
    await llm.emit_status(f"↑ {w.text} (before {id})")
    await llm.emit_listener_event('wordedit.word.insert_before', {'id': w.id, 'text': w.text, 'before_id': id})
    return f"Inserted [{w.id}] '{w.text}' before [{id}]\n\nCurrent buffer:\n{words.render()}"

  async def insert_after(id: str, text: str) -> str:
    """
    Insert a word or phrase after the word with the given ID.

    Args:
      id (str): The ID of the word to insert after
      text (str): The word or short phrase to insert
    """
    w = words.insert_after(id, text)
    if w is None:
      return f"Error: ID '{id}' not found"
    await llm.emit_status(f"↓ {w.text} (after {id})")
    await llm.emit_listener_event('wordedit.word.insert_after', {'id': w.id, 'text': w.text, 'after_id': id})
    return f"Inserted [{w.id}] '{w.text}' after [{id}]\n\nCurrent buffer:\n{words.render()}"

  async def update_word(id: str, text: str) -> str:
    """
    Update the text of the word with the given ID.

    Args:
      id (str): The ID of the word to update
      text (str): The new text for the word
    """
    if words.update(id, text):
      await llm.emit_status(f"✎ {id} → {text}")
      await llm.emit_listener_event('wordedit.word.update', {'id': id, 'text': text})
      return f"Updated [{id}] to '{text}'\n\nCurrent buffer:\n{words.render()}"
    return f"Error: ID '{id}' not found"

  async def delete_word(id: str) -> str:
    """
    Delete the word with the given ID from the buffer.

    Args:
      id (str): The ID of the word to delete
    """
    if words.delete(id):
      await llm.emit_status(f"✕ {id}")
      await llm.emit_listener_event('wordedit.word.delete', {'id': id})
      return f"Deleted [{id}]\n\nCurrent buffer:\n{words.render()}"
    return f"Error: ID '{id}' not found"

  tools.registry.set_local_tool('add_word', add_word)
  tools.registry.set_local_tool('insert_before', insert_before)
  tools.registry.set_local_tool('insert_after', insert_after)
  tools.registry.set_local_tool('update_word', update_word)
  tools.registry.set_local_tool('delete_word', delete_word)

  buffer_state = words.render() if words.words else "(empty)"
  chat.system(SYSTEM_PROMPT.format(buffer=buffer_state))

  # Force tool use for initial response
  llm.params['tool_choice'] = 'required'

  await llm.emit_message('<think>\n')
  await llm.emit_listener_event('wordedit.status', {'status': 'Building response'})

  # Phase 1: Build initial response
  max_retries = 3
  for attempt in range(max_retries):
    await llm.stream_final_completion(emit=True)

    if words.words:
      break

    if attempt < max_retries - 1:
      feedback = (
        "You didn't use any word tools, so I only saw empty response. "
        "You must use word tools when replying to me. "
        "Call add_word() now to build your response."
      )
      chat.user(feedback)
      await llm.emit_status(f"Retry {attempt + 2}/{max_retries}: prompting for tool use")

  # Phase 2: Review and edit
  if words.words:
    llm.params['tool_choice'] = 'auto'

    review_prompt = f"""Your draft response is complete. Here is the current buffer:

{words.render()}

Which reads as: "{words.to_text()}"

Now REVIEW your response critically:
- Is anything missing or incomplete?
- Are there awkward phrasings to fix?
- Should any words be reordered?

Use insert_before, insert_after, update_word, or delete_word to make improvements.
If the response is good as-is, simply stop (make no tool calls)."""

    chat.user(review_prompt)
    await llm.emit_status("Review phase...")
    await llm.emit_listener_event('wordedit.status', {'status': 'Reviewing and refining'})
    await llm.stream_final_completion(emit=True)

  await llm.emit_message('\n</think>\n\n')
  await llm.emit_listener_event('wordedit.status', {'status': 'Done'})

  final_text = words.to_text()
  if final_text:
    await llm.emit_message(final_text)
  else:
    await llm.emit_message('(No response generated - model did not use word tools)')
