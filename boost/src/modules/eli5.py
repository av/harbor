import llm
import log
import chat as ch
import config
import selection

ID_PREFIX = "eli5"
logger = log.setup_logger(ID_PREFIX)

eli5_prompt = """
My friend asked me this question: "{question}".
Explain it to me like I'm stupid. Explain every word and its specific impact on the question.
Do not asnwer the question, though, I want to figure it out myself.
I just need a simpler explanation thats easy to understand and follow.
""".strip()

answer_prompt = """
<instruction>
Given the initial question and its dedetailed explanation, provide the answer to the question.
</instruction>

<question>
{question}
</question>

<explanation>
{explanation}
</explanation>
""".strip()


async def apply(chat: 'ch.Chat', llm: 'llm.LLM'):
  strat = config.ELI5_STRAT.value
  strat_params = config.ELI5_STRAT_PARAMS.value
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
    return await llm.stream_final_completion()

  node = nodes[0]
  question = node.content

  await llm.emit_status("Explaining the question to myself...")
  explanation = await llm.stream_chat_completion(
    prompt=eli5_prompt.format(question=question),
  )

  await llm.emit_status('ELI5 Response')
  await llm.stream_final_completion(
    prompt=answer_prompt.format(
      question=question,
      explanation=explanation,
    )
  )
