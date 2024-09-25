ID_PREFIX = "unstable"

import chat as ch
import llm
import random

extreme_traits = [
  "Eccentric", "Obsessive", "Impulsive", "Paranoid", "Narcissistic",
  "Perfectionist", "Overly Sensitive", "Extremely Independent", "Manipulative",
  "Aloof"
]

temperaments = ["Choleric", "Melancholic", "Phlegmatic", "Sanguine"]

reply_styles = [
  "Blunt", "Sarcastic", "Overly Polite", "Evading", "Confrontational"
]


# Function to generate a random personality description
def random_personality():
  selected_traits = random.sample(extreme_traits, 3)
  selected_temperament = random.choice(temperaments)
  selected_reply_style = random.choice(reply_styles)

  description = (
    f"You are {', '.join(selected_traits)}. "
    f"You are known for yout {selected_temperament} temperament."
    f"You tend to write your replies in a {selected_reply_style} manner."
    f"Ensure that you reply to the User accordingly."
  )

  return description


async def apply(chat: 'ch.Chat', llm: 'llm.LLM'):
  personality = random_personality()
  chat.tail.ancestor().add_parent(
    ch.ChatNode(role="system", content=personality)
  )

  await llm.stream_final_completion()
