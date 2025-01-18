import chat as ch
import llm

ID_PREFIX = 'recpl'
ITERATIONS = 1

init_prompt = """
Fill the middle section of the plan that achieves a given objective using normal computer desktop.

Objective:
{objective}

Plan:
- Blank desktop with no applications open
- ...
- Output the final result to the User
""".strip()

init_expansion_prompt = """
Expand the non-atomic actions in the plan.
To do so, follow this procedure:
- Read an action
- Decide if it's already atomic or not (see examples below)
- If it's atomic, leave it as is
- If it's not atomic, expand it into smaller actions
- Move to the next action, repeat

Example atomic actions (do not expand, leave as is):
- Clicking (single, double, right, left, etc)
- Moving the mouse
- Keyboard input (typing, shortcuts, etc)
- Read one specific area on the screen (e.g. page header, a paragraph, side content, etc.)

Example non-atomic actions (expand these until they are atomic):
- Find the paragraph that contains the word "apple"
- Increase the font size of the text
- Read a whole webpage
""".strip()

repeat_expansion_prompt = """
Please expand the non-atomic actions in the plan further.
""".strip()


async def apply(chat: 'ch.Chat', llm: 'llm.LLM'):
  objective = chat.tail.content
  side_chat = ch.Chat(
    tail=ch.ChatNode(
      role='user',
      content=init_prompt.format(objective=objective)
    )
  )
  side_chat.llm = llm
  await side_chat.emit_status('Producing initial plan')
  await side_chat.emit_advance()

  side_chat.user(init_expansion_prompt)

  for i in range(ITERATIONS):
    await side_chat.emit_status(f'Expanding {i + 1}')
    await side_chat.emit_advance()
    side_chat.user(repeat_expansion_prompt)

  await llm.stream_final_completion(chat=side_chat)
