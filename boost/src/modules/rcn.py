# Recursive Certainty Validation - RCN
# aka "Are you sure?

from chat import Chat
from config import HARBOR_BOOST_RCN_STRAT, HARBOR_BOOST_RCN_STRAT_PARAMS
from selection import apply_selection_strategy

import llm
import log

logger = log.setup_logger(__name__)

ID_PREFIX = "rcn"


async def apply(chat: Chat, llm: 'llm.LLM'):
  strat = HARBOR_BOOST_RCN_STRAT.value
  strat_params = HARBOR_BOOST_RCN_STRAT_PARAMS.value
  debug_info = {
    "strat": strat,
    "strat_params": strat_params,
  }

  logger.debug(f"rcn: {debug_info}")

  nodes = apply_selection_strategy(
    chat,
    strategy=HARBOR_BOOST_RCN_STRAT.value,
    params=HARBOR_BOOST_RCN_STRAT_PARAMS.value
  )

  if (len(nodes) > 1):
    logger.warning(
      "RCN: Matched multiple nodes, only the first one will be processed."
    )

  if len(nodes) == 0:
    log.info("RCN: No nodes matched, skipping.")
    return llm.stream_chat_completion(chat)

  node = nodes[0]
  question = node.content

  rcn_chat = Chat.from_conversation(
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
  rcn_chat.llm = llm

  await rcn_chat.advance()
  rcn_chat.user("Are you sure?")
  await rcn_chat.advance()
  rcn_chat.user("Is this yout final answer?")
  await rcn_chat.advance()
  rcn_chat.user("Now prepare your final answer. Write it as a response to this message. Do not write anything else.")

  # This is streamed back
  return llm.stream_chat_completion(rcn_chat)
