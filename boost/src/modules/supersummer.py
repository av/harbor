from config import SUPERSUMMER_STRAT, SUPERSUMMER_STRAT_PARAMS, SUPERSUMMER_NUM_QUESTIONS, SUPERSUMMER_LENGTH

import llm
import log
import selection
import chat as ch

ID_PREFIX = "supersummer"

logger = log.setup_logger(__name__)

# Super Summer is based on the technique from this post:
# https://www.reddit.com/r/LocalLLaMA/comments/1ftjbz3/shockingly_good_superintelligent_summarization/
# This version, however was split into two parts to
# work better with the smaller LLMs

questions_prompt = """
<instruction>
Analyse the input text and generate {num_questions} essential questions that, when answered, capture the main points and core meaning of the text.
When formulating your questions:
  1. Address the central theme or argument
  2. Identify key supporting ideas
  3. Highlight important facts or evidence
  4. Reveal the author's purpose or perspective
  5. Explore any significant implications or conclusions.
There is no need to explain the answers to the questions, our explain why you chose them.
</instruction>

<input>
{input}
</input>
""".strip()

summer_prompt = """
<instruction>
You are a summarizer. You task is to write a summary of the input by answering a few essential questions.
Give detailed and thorogh answers, but don't forget that your summary must be coherent and readable.
The summary should have a length of {length}.
</instruction>

<input>
{input}
</input>

<questions>
{questions}
</questions>
""".strip()


async def apply(chat: 'ch.Chat', llm: 'llm.LLM'):
  strat = SUPERSUMMER_STRAT.value
  strat_params = SUPERSUMMER_STRAT_PARAMS.value
  num_questions = SUPERSUMMER_NUM_QUESTIONS.value
  length = SUPERSUMMER_LENGTH.value

  debug_info = {
    "strat": strat,
    "strat_params": strat_params,
    "num_questions": num_questions,
    "length": length
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

  await llm.emit_status('Generating questions...')
  questions = await llm.stream_chat_completion(
    prompt=questions_prompt.
    format(num_questions=num_questions, input=node.content)
  )

  await llm.emit_status('Generating summary...')
  await llm.stream_final_completion(
    prompt=summer_prompt.format(input=node.content, questions=questions, length=length)
  )
