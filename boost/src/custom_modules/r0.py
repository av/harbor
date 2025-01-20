import random

import chat as ch
import llm

ID_PREFIX = 'r0'

THOUGHT_ENTRIES = [
  "Let's start with thinking about ",
  'Let me think about ',
  'Let me consider ',
  "As a first thought - ",
  'First, let me think about ',
]

THOUGHT_LOOP = [
  'Let me reconsider...',
  'Another thought:',
  'Wait a moment!',
  'Wait, what about ',
  'Let me think of other possibilities...',
  'But wait, could there be another answer?',
  'Alternatively, ',
  'What if ',
  'Wait! I just thought of ',
  'From another perspective, ',
  'On a second thought, ',
  'Another idea:',
  'But what if we consider ',
  'Additionally, ',
]

THOUGHT_FINAL = [
  'After some thought, I think ',
  'After considering everything, I believe ',
  'As a final thought - ',
  'One last consideration:',
  'Finally, I think that ',
  'In conclusion, ',
]

THOUGHTS = 5

def random_element(arr):
  return arr[random.randint(0, len(arr) - 1)]

async def ensure_completion(chat: 'ch.Chat', **kwargs):
  response = ''
  while response.strip() == '':
    response = await chat.emit_advance(**kwargs)

async def apply(chat: 'ch.Chat', llm: 'llm.LLM'):
  extra_params = {}

  await chat.emit_status('Intro')
  intro = random_element(THOUGHT_ENTRIES)
  chat.assistant(intro)
  await llm.emit_message(intro)
  await ensure_completion(chat, params={
    **extra_params,
  })

  for i in range(THOUGHTS):
    await chat.emit_status('Thought ' + str(i + 1))
    starter = random_element(THOUGHT_LOOP)
    chat.assistant(starter)
    await llm.emit_message(starter)
    await ensure_completion(chat, params=extra_params)

  await chat.emit_status('Closing thought')
  final = random_element(THOUGHT_FINAL)
  chat.assistant(final)
  await llm.emit_message(final)
  await ensure_completion(chat, params=extra_params)

  await chat.emit_status('Final')
  chat.user(
    'Now, rewrite all messages above into a single coherent answer. Reply only with the revised answer and nothing else.'
  )
  await llm.stream_final_completion(chat=chat)
