import chat as ch
import llm

ID_PREFIX = 'clarity'

should_clarify_prompt = """
<instruction>
Is this question requires any clarification or is ready to be answered?
Reply only with "clarify" or "ready" and nothing else. Everything else will be ignored.
</instruction>

<question>
{question}
</question>
  """.strip()


async def apply(chat: 'ch.Chat', llm: 'llm.LLM'):
  iterations = 0
  max_iterations = 15

  side_chat = ch.Chat.from_conversation([chat.tail.message()])
  side_chat.llm = llm

  while iterations < max_iterations:
    iterations += 1
    side_chat.user(
      """
Are there any sources of ambiguity in my request?
Answer with "yes" or "no" and nothing else. Everything else will be ignored.
    """.strip()
    )
    await side_chat.advance()
    await llm.emit_status(f'Clarification: {side_chat.tail.content}')

    if side_chat.tail.contains('no'):
      break

    side_chat.user("""
Clarify the ambiguity you mentioned.
    """.strip())
    await side_chat.emit_advance()

    if iterations >= max_iterations:
      break

  side_chat.user('Now, please provide a clear answer to the question.')
  await side_chat.emit_advance()

  await llm.emit_status('Final')

  side_chat.user(
    """
Think trough the response you just gave. Is there anything wrong? If so, please correct it.
Otherwise, write down your final answer to my request.
    """.strip()
  )
  await llm.stream_final_completion(chat=chat)