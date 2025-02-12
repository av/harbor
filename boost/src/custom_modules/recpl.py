import chat as ch
import llm
from dataclasses import dataclass

# recpl - Recursive Plan Expansion
ID_PREFIX = 'recpl'
ITERATIONS = 8

@dataclass
class RecplGUI:
  init_plan: str = """
Fill the middle section of the plan that achieves a given objective using normal computer desktop.

Objective:
{objective}

Context:
- Linux desktop, Ubuntu with XFCE desktop environment
- No applications are open

Plan:
- Blank desktop with no applications open
- ...
- Output the final result to the User
""".strip()

  init_expansion: str = """
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

  continu_expansion: str = """
Please expand the non-atomic actions in the plan further.
""".strip()

@dataclass
class RecplReason:
  init_plan: str = """
Fill the middle section (denoted with "...") of the plan that should fulfill the objective.
You can not add any knowledge into the plan, leave it to the person that'll execute it later.
Every step must be a single short sentence.

Objective:
{objective}

Plan:
- Read the objective and understand it
- ...
- Output the final result
""".strip()

  init_expansion: str = """
Revise the plan.
To do so, follow this procedure:
- Read a step
- Decide if it's already atomic or not (see examples below)
- If it's atomic, leave it as is
- If it's not atomic, expand it into multiple steps
- Move to the next step, repeat

Examples of atomic steps (do not expand, leave as is):
- All required inputs are clearly defined
- Step can be accomplished in a single action
- There is only one way to interpret the step

Example non-atomic steps (expand these until they are atomic):
- Step relies on one or more inputs that are not yet defined
- There are unknowns or ambiguities in the step
- Step can be interpreted in multiple ways

Reply with the expanded plan and nothing else.
Every step must be a single short sentence.
""".strip()

  continue_expansion: str = """
Continue revising plan according to the procedure.
""".strip()

prompts = RecplReason()

async def call(chat: 'ch.Chat', llm: 'llm.LLM'):
  objective = chat.tail.content
  side_chat = ch.Chat(
    tail=ch.ChatNode(
      role='user',
      content=prompts.init_plan.format(objective=objective)
    )
  )
  side_chat.llm = llm
  await side_chat.emit_status('Producing initial plan')
  await side_chat.emit_advance()

  init_prompt = prompts.init_expansion.format(objective=objective)
  repeat_prompt = prompts.continue_expansion

  for i in range(ITERATIONS):
    prompt = init_prompt if i == 0 else repeat_prompt
    side_chat.user(prompt)
    await side_chat.emit_status(f'Expanding {i + 1}')
    await side_chat.emit_advance()

  return side_chat

async def apply(chat: 'ch.Chat', llm: 'llm.LLM'):
  await llm.emit_message('<think done="true">')
  final_chat = await call(chat, llm)
  chat.user('Address my message by following the plan below:')
  chat.user(final_chat.tail.content)
  await llm.emit_status('Final completion')
  await llm.emit_message('</think>')
  await llm.stream_final_completion(chat=chat)

