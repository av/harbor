import chat as ch
import llm

ID_PREFIX = '3t'


async def apply(chat: 'ch.Chat', llm: 'llm.LLM'):
  side_chat = ch.Chat(
    tail=ch.ChatNode(
      content="""
I will ask you to answer my question three times. Each time you will provide a different answer.
Try to use the chance to correct any mistakes you made in the previous answers.
  """.strip()
    )
  )
  side_chat.llm = llm

  side_chat.user('Here is the question:')
  side_chat.user(chat.tail.content)
  side_chat.user('Please provide the first answer to the question.')
  await side_chat.emit_status('First')
  await side_chat.emit_advance()

  side_chat.user(
    'Please provide the second answer to the question. Remember, it must be different from the first one.'
  )
  await side_chat.emit_status('Second')
  await side_chat.emit_advance()

  side_chat.user(
    'Please provide the third answer to the question. It must be different from the first two.'
  )
  await side_chat.emit_status('Third')
  await side_chat.emit_advance()

  side_chat.user(
    """
Now, think about the answers you provided. Is there anything wrong with them? Which one is the most correct?
What is the final answer to the question?
  """.strip()
  )
  await side_chat.emit_status('Final')
  await llm.stream_final_completion(chat=side_chat)
