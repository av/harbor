import chat
import llm
import log

# cex - Context Expansion
ID_PREFIX = "cex"
logger = log.setup_logger(ID_PREFIX)

async def apply(chat: 'chat.Chat', llm: 'llm.LLM'):
  repeats = 3
  content = chat.tail.content

  repeated_content = await llm.chat_completion(
    prompt="""
Take a below content and rewrite it word-by-word {repeats} times.
However, for every repetition, you will choose analogous words or synonyms.
Do not answer to the content itself, only rewrite it word-by-word.
Do not write any comments or annotations, only reply with the rewritten content and nothing else.

Example:
"The quick brown fox jumps over the lazy dog."
- The swift russet fox leaps across the idle hound.
- The nimble tawny fox bounds over the lethargic canine.
- The agile copper fox vaults above the sluggish mutt.

Content:
{content}
""".strip(),
    content=content,
    repeats=repeats,
    resolve=True
  )

  await llm.emit_message(f"{repeated_content}\n")

  chat.user(f"""
Since you have a hard time understanding things, here's the same message as above, but rephrased word-by-word {repeats} times.
{repeated_content}
  """)
  words = chat.tail.content.split()
  repeated = ' '.join([' '.join([word] * repeats) for word in words])
  chat.tail.content = repeated

  await llm.emit_message("\n---\n")
  await llm.stream_final_completion(chat=chat)
