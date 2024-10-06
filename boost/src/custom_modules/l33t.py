import llm
import chat as ch

ID_PREFIX = 'l33t'

async def apply(chat: 'ch.Chat', llm: 'llm.LLM'):
  side_chat = ch.Chat.from_conversation([chat.tail.message()])
  side_chat.llm = llm

  await llm.emit_status('l33t speak...')
  side_chat.user("Rewrite my previous message in light leetspeak, ensure it is still readable by an average user, though.")
  await side_chat.emit_advance()
  await llm.emit_status('l33t answer...')
  side_chat.user(
    "Now write an answer for that message, also use l33t speak, but not too much. Refer to original message for clarity."
  )
  await side_chat.emit_advance()
  await llm.emit_status('Unl33t...')
  side_chat.user('Now write a final answer, in plain English')
  await side_chat.emit_advance()