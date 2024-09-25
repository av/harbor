# Recursive Certainty Validation - RCN
# aka "Are you sure?

from config import RCN_STRAT, RCN_STRAT_PARAMS

import llm
import log
import chat as ch
import selection

logger = log.setup_logger(__name__)

ID_PREFIX = "rcn"


async def apply(chat: 'ch.Chat', llm: 'llm.LLM'):
  strat = RCN_STRAT.value
  strat_params = RCN_STRAT_PARAMS.value
  debug_info = {
    "strat": strat,
    "strat_params": strat_params,
  }

  logger.debug(f"{ID_PREFIX}: {debug_info}")
  nodes = selection.apply_strategy(chat, strategy=strat, params=strat_params)

  if (len(nodes) > 1):
    logger.warning(
      f"{ID_PREFIX}: Matched multiple nodes, only the first one will be processed."
    )

  if len(nodes) == 0:
    log.info(f"{ID_PREFIX}: No nodes matched, skipping.")
    return llm.stream_chat_completion(chat)

  node = nodes[0]
  question = node.content

  output = chat.Chat.from_conversation(
    [
      {
        "role":
          "system",
      "content":
          """
YOU HAVE LIMITATIONS AS AN LLM. DO NOT OVERCOMPLICATE THINGS. YOU MAKE MISTAKES ALL THE TIME, SO BE CAREFUL IN YOUR REASONING.
WHEN SOLVING PROBLEMS - DECOMPOSE THEM INTO SMALLER PARTS. SOLVE PARTS ONE BY ONE SEQUENTIALLY.
DECLARE THE INITIAL STATE, MODIFY IT ONE STEP AT A TIME. CHECK THE RESULT AFTER EACH MODIFICATION.
DO NOT SAY YOU DOUBLE-CHECKED AND TRIPLE-CHECKED WITHOUT ACTUALLY DOING SO.
""".strip()
      }, {
        "role":
          "user",
        "content":
          f"""
Take this question:
{question}

Describe the meaning of every word in relation to the question. Paraphrase the question two times. Then provide a solution.
""".strip()
      }
    ]
  )
  output.llm = llm

  await output.advance()
  output.user("Are you sure?")
  await output.advance()
  output.user("Is this yout final answer?")
  await output.advance()
  output.user(
    "Now prepare your final answer. Write it as a response to this message. Do not write anything else."
  )

  await llm.stream_final_completion(chat=output)
