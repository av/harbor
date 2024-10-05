import random

import chat as ch
import llm

ID_PREFIX = 'wswp'

def swap_words(**args) -> str:
  text = args['text']
  probability = args['probability']

  words = text.split(' ')

  for i in range(len(words) - 1):
    if random.random() < probability:
      # Swap current word with the next one
      words[i], words[i + 1] = words[i + 1], words[i]

  return ' '.join(words)


async def apply(chat: 'ch.Chat', llm: 'llm.LLM'):
  chat.tail.content = swap_words(text=chat.tail.content, probability=0.15)
  await llm.emit_status(f'wswp: {chat.tail.content}')
  await llm.stream_final_completion()
