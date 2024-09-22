# g1 - the approach from: https://github.com/bklieger-groq/g1
# Harbor also uses same logic for ol1 service

from chat import Chat, ChatNode
from config import HARBOR_BOOST_G1_STRAT, HARBOR_BOOST_G1_STRAT_PARAMS, HARBOR_BOOST_G1_MAX_STEPS
from selection import apply_selection_strategy

import llm
import log

logger = log.setup_logger(__name__)

ID_PREFIX = "g1"


async def apply(chat: Chat, llm: 'llm.LLM'):
  strat = HARBOR_BOOST_G1_STRAT.value
  strat_params = HARBOR_BOOST_G1_STRAT_PARAMS.value
  max_steps = HARBOR_BOOST_G1_MAX_STEPS.value
  debug_info = {
    "strat": strat,
    "strat_params": strat_params,
    "max_steps": max_steps,
  }

  logger.debug(f"g1: {debug_info}")

  nodes = apply_selection_strategy(
    chat,
    strategy=HARBOR_BOOST_G1_STRAT.value,
    params=HARBOR_BOOST_G1_STRAT_PARAMS.value
  )

  if (len(nodes) > 1):
    logger.warning(
      "G1: Matched multiple nodes, only the first one will be processed."
    )

  if len(nodes) == 0:
    log.info("G1: No nodes matched, skipping.")
    return llm.stream_chat_completion(chat)

  node = nodes[0]

  g1_chat = Chat(
    llm=llm,
    tail=ChatNode(
      role="system",
      content=
      f"""You are an expert AI assistant that explains your reasoning step by step. For each step, provide a title that describes what you're doing in that step, along with the content. Decide if you need another step or if you're ready to give the final answer. In your response write "ACTION" followed by either 'continue' or 'final_answer'. USE AS MANY REASONING STEPS AS POSSIBLE. AT LEAST 3. BE AWARE OF YOUR LIMITATIONS AS AN LLM AND WHAT YOU CAN AND CANNOT DO. IN YOUR REASONING, INCLUDE EXPLORATION OF ALTERNATIVE ANSWERS. CONSIDER YOU MAY BE WRONG, AND IF YOU ARE WRONG IN YOUR REASONING, WHERE IT WOULD BE. FULLY TEST ALL OTHER POSSIBILITIES. YOU CAN BE WRONG. WHEN YOU SAY YOU ARE RE-EXAMINING, ACTUALLY RE-EXAMINE, AND USE ANOTHER APPROACH TO DO SO. DO NOT JUST SAY YOU ARE RE-EXAMINING. USE AT LEAST 3 METHODS TO DERIVE THE ANSWER. USE BEST PRACTICES."""
      .strip()
    )
  )
  g1_chat.user(node.content)
  g1_chat.assistant(
    "Thank you! I will now think step by step following my instructions, starting at the beginning after decomposing the problem."
  )

  while True:
    await g1_chat.advance()

    tail = g1_chat.tail
    if tail.role == "assistant" and "final_answer" in tail.content:
      break

    if len(g1_chat.history()) >= max_steps:
      break

  g1_chat.user("Please provide the final answer based on your reasoning above. You don't have to mention 'ACTION' in your response.")

  return llm.stream_chat_completion(g1_chat)
