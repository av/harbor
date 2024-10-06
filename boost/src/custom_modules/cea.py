import random

import chat as ch
import llm
import log

ID_PREFIX = 'cea'    # 'cellular automata'


def cellular_automata(rule, initial_state, generations):
  """
    Runs a one-dimensional cellular automata and records results in binary,
    allowing the state to grow.

    Args:
        rule (int): The rule number for the cellular automata (0-255).
        initial_state (list): The initial state of the cellular automata.
        generations (int): The number of generations to run.

    Returns:
        list: A list of binary strings representing the state of the cellular automata at each generation.
    """
  # Convert the rule number to a binary string and pad with zeros to 8 bits
  rule_binary = format(rule, '08b')

  # Initialize the list to store the results
  results = ["".join(map(str, initial_state))]

  # Run the cellular automata for the specified number of generations
  current_state = initial_state.copy()
  for _ in range(generations):
    # Initialize the next state with a zero on each end
    next_state = [0] + current_state + [0]

    # Apply the rule to each cell in the current state
    for i in range(1, len(next_state) - 1):
      # Get the left, center, and right cells
      left = current_state[i - 2] if i > 1 else 0
      center = current_state[i - 1]
      right = current_state[i] if i < len(current_state) else 0

      # Convert the left, center, and right cells to a binary string
      neighborhood = f"{left}{center}{right}"

      # Get the next state of the cell based on the rule
      next_state[i] = int(rule_binary[7 - int(neighborhood, 2)])

    # Update the current state and append the next state to the results
    current_state = next_state
    results.append("".join(map(str, next_state)))

  return results

def render_ca(results):
  """
    Renders the results of a cellular automata as a string.

    Args:
        results (list): A list of binary strings representing the state of the cellular automata at each generation.

    Returns:
        str: A string representation of the cellular automata results.
    """
  return join.join(["".join(["|" if cell == "1" else "." for cell in result]) for result in results])



initial_state = [1]
join = '\n'


async def apply(chat: 'ch.Chat', llm: 'llm.LLM'):
  rule = int(llm.boost_params.get('cea_rule', '73'))
  gens = int(llm.boost_params.get('cea_generations', '32'))

  chat.user(
    f"""
Before completing my request, please think for a while.
    """.strip()
  )
  chat.assistant(
    f"""Good idea! Let me think...

```thoughts
{render_ca(cellular_automata(rule, initial_state, gens))}
```

"""
  )
  await llm.emit_message(chat.tail.content)
  chat.user(f"""
Now, please address my request.
    """.strip())
  await llm.stream_final_completion()
