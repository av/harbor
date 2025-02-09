import chat as ch
import llm

ID_PREFIX = 'crystal'

query_prompt = """
[TASK]
Analyse given conversation. Rewrite it as a single standalone message from the user to the assistant.
Your reply must a relatively short message that captures the essence of the conversation and the user's intent at this point.

[CONVERSATION]
{conversation}
"""

decomposition_prompt = """
[ROLE]
Act as three experts debating:
1. Analyst specializing in edge cases
2. Engineer focused on implementation details
3. Philosopher examining fundamental assumptions

[TASK]
For problem X, have each expert present their perspective, then synthesize consensus.
"""

async def apply(chat: 'ch.Chat', llm: 'llm.LLM'):
  crystal_chat = ch.Chat(tail=ch.ChatNode(role="user", content=""))
  question = await llm.chat_completion(
    prompt=query_prompt,
    conversation=chat,
    resolve=True
  )

  await llm.emit_status(question)

  crystal_chat.user(question)
  crystal_chat.system(decomposition_prompt)

  await llm.stream_final_completion(
    chat=crystal_chat
  )