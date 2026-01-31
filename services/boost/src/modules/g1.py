# g1 - the approach from: https://github.com/bklieger-groq/g1
# Harbor also uses same logic for ol1 service

from config import G1_STRAT, G1_STRAT_PARAMS, G1_MAX_STEPS

import llm
import log
import selection
import chat as ch

logger = log.setup_logger(__name__)

ID_PREFIX = "g1"
DOCS = """
Dynamic Chain-of-Thought pattern.

See [original implementation for Grok](https://github.com/bklieger-groq/g1). Harbor also has a [dedicated `ol1` service](./2.3.19-Satellite:-ol1) (UI only) that implements the same technique.

```bash
# Enable the module
harbor boost modules add g1
```

**Parameters**

- `max_steps` - Maximum amount of iterations for self-reflection, default is 15
- `strat` - strategy for selection of the messages to rewrite. Default is `match`
  - `all` - match all messages
  - `first` - match first message regardless of the role
  - `last` - match last message regardless of the role
  - `any` - match one random message
  - `percentage` - match a percentage of random messages from the conversation
  - `user` - match all user messages
  - `match` - use a filter to match messages
- `strat_params` - parameters (filter) for the selection strategy. Default matches all user messages
  - `percentage` - for `percentage` strat - the percentage of messages to match, default is `50`
  - `index` - for `match` strat - the index of the message to match
  - `role` - for `match` strat - the role of the message to match
  - `substring` - for `match` strat - will match messages containing the substring
"""


async def apply(chat: 'ch.Chat', llm: 'llm.LLM'):
  strat = G1_STRAT.value
  strat_params = G1_STRAT_PARAMS.value
  max_steps = G1_MAX_STEPS.value
  debug_info = {
    "strat": strat,
    "strat_params": strat_params,
    "max_steps": max_steps,
  }

  logger.debug(f"{ID_PREFIX}: {debug_info}")

  nodes = selection.apply_strategy(chat, strategy=strat, params=strat_params)

  if (len(nodes) > 1):
    logger.warning(
      f"{ID_PREFIX}: Matched multiple nodes, only the first one will be processed."
    )

  if len(nodes) == 0:
    log.info(f"{ID_PREFIX}: No nodes matched, skipping.")
    return await llm.stream_final_completion()

  node = nodes[0]

  output = ch.Chat(
    llm=llm,
    tail=ch.ChatNode(
      role="system",
      content=
      f"""You are an expert AI assistant that explains your reasoning step by step. For each step, provide a title that describes what you're doing in that step, along with the content. Decide if you need another step or if you're ready to give the final answer. In your response write "ACTION" followed by either 'continue' or 'final_answer'. USE AS MANY REASONING STEPS AS POSSIBLE. AT LEAST 3. BE AWARE OF YOUR LIMITATIONS AS AN LLM AND WHAT YOU CAN AND CANNOT DO. IN YOUR REASONING, INCLUDE EXPLORATION OF ALTERNATIVE ANSWERS. CONSIDER YOU MAY BE WRONG, AND IF YOU ARE WRONG IN YOUR REASONING, WHERE IT WOULD BE. FULLY TEST ALL OTHER POSSIBILITIES. YOU CAN BE WRONG. WHEN YOU SAY YOU ARE RE-EXAMINING, ACTUALLY RE-EXAMINE, AND USE ANOTHER APPROACH TO DO SO. DO NOT JUST SAY YOU ARE RE-EXAMINING. USE AT LEAST 3 METHODS TO DERIVE THE ANSWER. USE BEST PRACTICES."""
      .strip()
    )
  )
  output.user(node.content)
  output.assistant(
    "Thank you! I will now think step by step following my instructions, starting at the beginning after decomposing the problem."
  )

  steps = 0
  while True:
    await llm.emit_status(f'Step: {steps + 1}')
    await output.emit_advance()
    steps += 1

    if output.tail.contains("final_answer") or steps >= max_steps:
      break

  output.user(
    "Please provide the final answer based on your reasoning above. You don't have to mention 'ACTION' in your response."
  )
  await llm.emit_status('Final Answer')
  await llm.stream_final_completion(chat=output)
