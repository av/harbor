import asyncio
import random
import chat as ch
import llm
import os

ID_PREFIX = 'dnd'

current_dir = os.path.dirname(os.path.abspath(__file__))
artifact_path = os.path.join(
  current_dir, '..', 'custom_modules', 'artifacts', 'dnd_mini.html'
)


async def apply(chat: 'ch.Chat', llm: 'llm.LLM'):
  dice = '2d20'
  difficulty_class = random.randint(10, 40)
  result = [
    random.randint(1, 20),
    random.randint(1, 20),
  ]
  passed = result[0] + result[1] >= difficulty_class
  dice_notation = f"{dice}@{','.join(map(str, result))}"

  skill = await llm.chat_completion(
    prompt="""
<instruction>
Read the "message" carefully and thoroughly.
Now, as a game master you will think of a skill check the player must pass to address that message.
The check name is a few words long and closely related to the message, it's specific.
Take your first option - throw it away, it's too generic and shallow.
Take your second option - throw it away, it's trying too hard to be clever.
Proceed throwing options away until you have a skill name that just "perfect".
Now, pinch a tiny bit of sarcasm on top - that's the one.
Reply with the skill name and nothing else.
</instruction>

<message>
{message}
</message>
    """,
    message=chat.tail.content,
    params={
      "temperature": 1.0,
    },
    resolve=True,
  )

  with open(artifact_path, 'r') as file:
    artifact = file.read()
  await llm.emit_artifact(
    artifact
      .replace('<<listener_id>>', llm.id)
      .replace('<<skill_name>>', skill.strip())
      .replace('<<difficulty_class>>', str(difficulty_class))
      .replace('<<result>>', 'passed' if passed else 'failed')
      .replace('<<dice>>', dice_notation)
  )
  await llm.emit_status('Rolling...')
  # Wait for the artifact to be loaded and
  # ready to accept messages
  await asyncio.sleep(3.0)

  if passed:
    chat.user("""
Please answer to my message as if you passed a "{skill}" check.
    """.format(skill=skill, dice=dice_notation, dc=difficulty_class))
  else:
    chat.user("""
Please answer to my message as if you failed a "{skill}" check.
Since you failed, your reply should actually fail to address the message as well.
    """.format(skill=skill, dice=dice_notation, dc=difficulty_class))

  await llm.stream_final_completion()
