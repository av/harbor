from pydantic import BaseModel, Field

import chat
import llm
import log

# cex - Context Expansion
ID_PREFIX = "cex"
logger = log.setup_logger(ID_PREFIX)

variants_prompt = """
Take below content and rewrite it word-by-word {repeats} times.
Choose analogous words or synonyms for every repetition.
Do not answer to the content itself, only rewrite it word-by-word.
You must reply with a JSON array with {repeats} strings, each item being a paraphrased sentence.

Example:
"The quick brown fox jumps over the lazy dog."
[
  "The swift russet fox leaps across the idle hound.",
  "The nimble tawny fox bounds over the lethargic canine.",
  "The agile copper fox vaults above the sluggish mutt."
]

Content:
{content}
"""


class VariantsResponse(BaseModel):
  variants: list[str] = Field(
    default_factory=list,
    description="List of paraphrased sentences based on the original content."
  )


async def apply(chat: 'chat.Chat', llm: 'llm.LLM'):
  """
  `cex` - Context Expansion.

  Rephrases initial input content multiple times, generating variants of the original text.
  The idea is that reprojections of the original content can help avoiding otherwise overfit answers.
  """

  repeats = 3
  content = chat.tail.content

  variants_response = await llm.chat_completion(
    prompt=variants_prompt.strip(),
    content=content,
    repeats=repeats,
    schema=VariantsResponse,
    resolve=True
  )
  variants = VariantsResponse(**variants_response)
  responses = []

  for variant in variants.variants:
    response = await llm.chat_completion(prompt=variant, resolve=True)
    responses.append(response)

  variants_text = [f"- {response}" for response in responses]
  chat.user(f"""
Synthesize your answer based on the following options:
{variants_text}
""")
  await llm.stream_final_completion()
