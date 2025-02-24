import random

import chat as ch
import llm

ID_PREFIX = 'r0'

THOUGHT_ENTRIES = [
  'What ',
  'Let me ',
  'Considering ',
  'As a first thought - ',
  'Wow, ',
  'I think ',
  'Granted ',
  'Given ',
  'Since ',
  'In light of ',
]

THOUGHT_LOOP = [
  'So ',
  'Hmm, ',
  'But wait, ',
  'I think ',
  'This is ',
  'Another angle ',
  'Alternatively, ',
  'Perhaps ',
  'This ',
  'Unless ',
  'From another perspective, ',
  'On a second thought, ',
  'Wait a minute, ',
  'Maybe ',
  'This seems ',
  'But since ',
  'Let me try ',
  'What ',
  'Let me ',
  'Considering ',
  'As a first thought - ',
  'I think ',
  'Granted ',
  'Given ',
  'Since ',
  'In light of ',
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
  extra_params = {
    'temperature': 1.0
  }

  await llm.emit_message('\n<think>\n')
  chat.system(
    '''
When you see an incomplete message from yourself, you will complete it into a coherent thought exactly where it left off.
You will use that as a chance to be critical of your own thoughts.
Being aware of your own limitations helps you avoiding them.
Think completely freely, you'll be given a chance to revise your thoughts.
You will not repeat previous conclusions blindly.
'''
  )
  # await chat.emit_status('Intro')
  intro = random_element(THOUGHT_ENTRIES)
  chat.assistant(intro)
  await llm.emit_message(intro)
  await ensure_completion(chat, params={
    **extra_params,
  })

  for i in range(THOUGHTS):
    starter = random_element(THOUGHT_LOOP)
    chat.assistant(starter)
    await llm.emit_message('\n' + starter + ' ')
    await ensure_completion(chat, params=extra_params)

  final = random_element(THOUGHT_FINAL)
  chat.assistant(final)
  await llm.emit_message(final)
  await ensure_completion(chat, params=extra_params)

  chat.user(
    'Now, rewrite all messages above into a single coherent answer. Reply only with the revised answer and nothing else. You can give a longer answer if you want.'
  )
  await llm.emit_message('\n</think>\n')
  await llm.stream_final_completion(chat=chat)
