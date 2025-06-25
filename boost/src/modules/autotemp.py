# This workflow is very loosely based on
# https://github.com/amanvirparhar/thermoask/blob/main/main.py

import log
import chat as ch
import llm
import tools
import tools.registry

ID_PREFIX = 'autotemp'

logger = log.setup_logger(ID_PREFIX)

choose_temperature_prompt = """
Dynamically adjust your temperature setting during responses using the `set_temperature` tool.

Temperature Guidelines:
- **High (0.8-1.0):** For creative tasks (e.g., creative writing, brainstorming).
- **Medium (0.4-0.7):** For balanced tasks (e.g., summarization, translation, general conversation).
- **Low (0.0-0.3):** For precise tasks (e.g., factual questions, code generation, technical explanations, reasoning).

Begin each response by setting an initial temperature suitable for the overall task. Adjust temperature dynamically for different parts of your response to optimize results.
"""

async def apply(chat: 'ch.Chat', llm: 'llm.LLM'):
  if 'qwen3' in llm.model:
    chat.system('/no_think')

  async def set_temperature(
    temperature: float,
    reason: str
  ):
    """
    Allows you to choose the temperature for next portion of your response.
    After calling this tool, you must proceed replying in text, otherwise it's for naught.

    Args:
      temperature (float): The temperature to set for the next portion of the response. Should be between 0.0 and 1.0.
      reason (str): Short (3-5 words) explanation of why the temperature is being set.
    """

    desired_temperature = float(temperature)
    current_temperature = llm.params.get('temperature')

    if current_temperature is not None and abs(current_temperature - desired_temperature) < 0.01:
      return f"Temperature is already set to {desired_temperature}. Are you using the tool correctly?"

    llm.params['temperature'] = desired_temperature
    await llm.emit_status(f'Temperature {desired_temperature}\nReason: {reason}')
    return f"Temperature is now set to {desired_temperature} because: {reason}"

  # Add the tool and the prompt
  tools.registry.set_local_tool('set_temperature', set_temperature)
  chat.system(choose_temperature_prompt)

  await llm.stream_final_completion()
