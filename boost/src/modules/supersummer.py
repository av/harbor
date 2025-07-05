from config import SUPERSUMMER_STRAT, SUPERSUMMER_STRAT_PARAMS, SUPERSUMMER_NUM_QUESTIONS, SUPERSUMMER_LENGTH

import llm
import log
import selection
import chat as ch

ID_PREFIX = "supersummer"
DOCS = """
Based on a technique of generation of a summary of the given given content from key questions. The module will ask the LLM to provide a given amount of key questions and then will use them to guide the generation of the summary.

**Parameters**

`supersummer` module supports selection strategy parameters identical to `mcts`, `g1`, and `rcn` modules, just under the `boost.supersummer` prefix.

```bash
# Strategy to find the message to start from
harbor config set boost.supersummer.strat match
# Match last user message, for example
harbor config set boost.supersummer.strat_params role=user,index=-1
```

In addition to that, it's possible to adjust number of questions the model will generate, as well as the desired length of the summary.

```bash
# Number of questions to generate
harbor config set boost.supersummer.questions 3
# Length of the summary, you can use any
# textual specification, like "one paragraph"
harbor config set boost.supersummer.length "few paragraphs"
```

Here're sample questions and summary that `supersummer` generated from Harbor's readme:

<details>

<summary>Sample questions and summary</summary>

### Questions

**What is Harbor, and what are its primary functions?**
(This question addresses the central theme or argument of the text, which is to introduce Harbor as a containerized LLM toolkit.)

**What services can be managed with Harbor, and how does it facilitate their use?**
(This question highlights important facts or evidence, such as the various services listed in the "Services" section, and how Harbor enables easy management and usage of these services.)

**How does Harbor simplify local LLM development and experimentation?**
(This question reveals the author's purpose or perspective, which is to make local LLM development more convenient and streamlined by providing a unified CLI interface for managing services and configurations.)

**What benefits does Harbor provide over using individual Docker Compose files or Linux administration commands?**
(This question explores any significant implications or conclusions of using Harbor, such as the convenience factor and workflow centralisation it offers.)

**Can Harbor be used in conjunction with existing Docker setups, or is it intended to replace them entirely?**
(This question highlights important facts or evidence about Harbor's purpose and scope, such as its ability to co-exist with existing Docker setups and provide added value through its convenience features.)

### Summary

Harbor is a containerized Long-Short-Memory (LLM) toolkit that enables effortless management of LLM backends, APIs, frontends, and services. Developed as an open-source project, Harbor consists of a Command-Line Interface (CLI) and a companion application to help manage and run AI services in a unified manner.

Harbor offers several key features:

- **Managed Services**: The platform allows users to easily manage various LLM-related services, such as UIs (User Interfaces), Backends, Frontends, and Satellites.
- **Unified CLI Interface**: Harbor provides a single command-line interface for managing multiple services, eliminating the need for manual configuration and streamlining development workflows.
- **Convenience Utilities**: A range of convenience tools helps users manage LLM-related tasks efficiently, such as setting up services, debugging, creating URLs, and establishing network tunnels.
- **Cache Sharing and Reuse**: Harbor shares and reuses host caches, significantly enhancing model performance and reducing memory consumption across supported services (e.g., Hugging Face models, Ollama).
- **Config Profiles**: The application allows users to manage multiple configuration profiles for different development tasks or projects.

Harbor's purpose is not only to provide a convenient platform but also to simplify local LLM development by making it easier to setup and experiment with various LLM-related services. As such, Harbor can perfectly align with existing Docker setups and offers several benefits over manual Linux administration commands, like ease of use and streamlined configurations management.

As the author implies, the main benefit of using Harbor lies in its ability to simplify local LLM development and reduce time required for experiments and prototyping steps in a unified and convenient setup.

</details>
"""

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
    prompt=summer_prompt.
    format(input=node.content, questions=questions, length=length)
  )
