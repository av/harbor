from pydantic import BaseModel, Field
from typing import Optional, List, Literal

import llm
import log
import chat as ch

ID_PREFIX = 'ow'

logger = log.setup_logger(ID_PREFIX)


class InsertWordSchema(BaseModel):
  type: Literal["insert_word"]
  word: str = Field(description="Word to insert", min_length=1)
  position: int = Field(
    description="Index to insert at, or append if not provided"
  )


class ReplaceWordSchema(BaseModel):
  type: Literal["replace_word"]
  index: int = Field(description="Index of word to replace")
  new_word: str = Field(description="New word to replace with", min_length=1)


class RemoveWordSchema(BaseModel):
  type: Literal["remove_word"]
  index: int = Field(description="Index of word to remove")


class ProgramSchema(BaseModel):
  type: Literal["program"]
  operations: List[InsertWordSchema | ReplaceWordSchema |
                   RemoveWordSchema] = Field(
                     description="List of operations to perform",
                     min_items=1,
                     max_items=2
                   )


class WordOperations:

  def __init__(self):
    self.words = []

  def insert_word(self, word, position=None):
    if position is None:
      self.words.append(word)
    else:
      self.words.insert(position, word)

  def replace_word(self, index, new_word):
    if 0 <= index < len(self.words):
      self.words[index] = new_word

  def remove_word(self, index):
    if 0 <= index < len(self.words):
      self.words.pop(index)

  def get_words(self):
    return self.words.copy()

  def clear_words(self):
    self.words.clear()

  def execute_program(self, program: ProgramSchema):
    for op in program.operations:
      if isinstance(op, InsertWordSchema):
        self.insert_word(op.word, op.position)
      elif isinstance(op, ReplaceWordSchema):
        self.replace_word(op.index, op.new_word)
      elif isinstance(op, RemoveWordSchema):
        self.remove_word(op.index)

  def to_prompt(self):
    return "\n".join(f"{i}. {word}" for i, word in enumerate(self.words))


edit_prompt = """
[TASK]
You will reply to the [QUERY], but will do so indirectly and in multiple steps.
During every step, you're given a response from the preivous step decomposed into a list individual words.
You can modify this list of words by writing a program that manipulates the list of words.
The program is a JSON object matching the [FORMAT] schema.

[QUERY]
"{query}"

[RESPONSE]
{words}

[FORMAT]
Respond with JSON that follows this schema:
{{
  "type": "program",
  "operations": [
  // Array of operation objects with required 'type' field and operation-specific fields
  // Examples:
  // {{"type": "insert_word", "word": "hello", "position": 0}}
  // {{"type": "replace_word", "index": 1, "new_word": "world"}}
  // {{"type": "remove_word", "index": 0}}
  ]
}}

[FINAL]
In the end, the list of words should address the user query. Godspeed!
"""


async def apply(chat: 'ch.Chat', llm: 'llm.LLM'):
  word_ops = WordOperations()

  for _ in range(5):
    program_json = await llm.chat_completion(
      prompt=edit_prompt,
      query=chat.tail.content,
      words=word_ops.to_prompt(),
      schema=ProgramSchema,
      resolve=True
    )
    await llm.emit_status(word_ops.to_prompt())
    program = ProgramSchema.parse_obj(program_json)
    await llm.emit_status(program)
    word_ops.execute_program(program)

  await llm.emit_message(" ".join(word_ops.get_words()))
