from pydantic import BaseModel, Field

import asyncio

import os
import random
from enum import Enum

import log
import chat as ch
import llm

ID_PREFIX = 'ponder'
DOCS = """
![ponder](./boost-ponder.png)

`ponder` is similar to the `concept` module, but with a different approach to building of the concept graph.

```bash
# Standalone usage
docker run \\
  -e "HARBOR_BOOST_OPENAI_URLS=http://172.17.0.1:11434/v1" \\
  -e "HARBOR_BOOST_OPENAI_KEYS=sk-ollama" \\
  -e "HARBOR_BOOST_PUBLIC_URL=http://localhost:8004" \\
  -e "HARBOR_BOOST_MODULES=ponder" \\
  -p 8004:8000 \\
  ghcr.io/av/harbor-boost:latest
```
"""

logger = log.setup_logger(ID_PREFIX)
current_dir = os.path.dirname(os.path.abspath(__file__))
artifact_path = os.path.join(
  current_dir,
  '..',
  'custom_modules',
  'artifacts',
  'nbs_mini.html',
)

concepts_prompt = """
<instruction>
Think of another concept that will help you in the conversation below.
Concept should match conversation complexity and energy.
Focus on "aha" moments, insights, or new ideas that can be explored, not obvious or trivial concepts.
Do not repeat any concepts that have already been suggested.
Do not include any additional text or explanations.
Respond with 1-3 words that describe the concept.
</instruction>

<input name="conversation">
{conversation}
</input>

<input name="concepts">
{concepts}
</input>
"""

strategies_prompt = """
<instruction>
Think of another strategy to use to continue the conversation below.
Should be based on the problem complexity, domain knowledge, reasoning type needed, your expertise, and the conversation context.
Focus on things that are beyound the obvious, something that you wouldn't consider unless given this task.
Do not repeat any strategies that have already been suggested.
Do not include any additional text or explanations.
Respond with 1-3 words that describe the strategy.
</instruction>

<input name="conversation">
{conversation}
</input>

<input name="concepts">
{concepts}
</input>
"""

topics_prompt = """
<instruction>
Suggest a topic that user wants to discuss based on the conversation below.
Focus on topics that are relevant to the conversation, but will help you explore new areas or deepen the discussion.
Do not repeat any topics that have already been suggested.
Do not include any additional text or explanations.
Respond with 1-3 words that describe the topic.
Topic shouldn't be random, if nothing else - ask questions.
</instruction>

<input name="conversation">
{conversation}
</input>

<input name="concepts">
{concepts}
</input>
"""

pick_next_concept_schema = """
<instruction>
Pick one concept from the list below that is the most important for the conversation.
</instruction>

<input name="conversation">
{conversation}
</input>

<input name="concepts">
{concepts}
</input>

Reply with a JSON object in a shape of:
{{ concept: "<concept>" }}
"""

follow_plan_prompt = """
<instruction>
Continue youe conversation with the user according to the plan below.
No need to ack this instruciton, just continue the conversation.
</instruction>

<input name="plan">
{plan}
</input>

<input name="conversation">
{conversation}
</input>
"""


class PonderConfig(BaseModel):
  concepts: int = Field(
    default=8,
    description='Number of concepts to suggest in each iteration.',
  )
  strategies: int = Field(
    default=4,
    description='Number of strategies to suggest in each iteration.',
  )
  topics: int = Field(
    default=12,
    description='Number of topics to suggest in each iteration.',
  )
  links: int = Field(
    default=8,
    description='Number of links to create between concepts.',
  )


async def short_pause():
  await asyncio.sleep(random.uniform(0.01, 0.6))


async def apply(chat: 'ch.Chat', llm: 'llm.LLM'):
  cfg = PonderConfig()
  exploration_params = {
    'temperature': 1.0,
  }

  with open(artifact_path, 'r') as f:
    artifact = f.read()

  await llm.emit_artifact(artifact)
  await llm.start_thinking()
  await llm.emit_message('\n### Concepts\n')
  concepts = []

  for _ in range(cfg.concepts):
    concept = await llm.chat_completion(
      prompt=concepts_prompt,
      conversation=chat,
      concepts=', '.join(concepts) if concepts else 'No concepts yet',
      params=exploration_params,
      resolve=True,
    )
    concept = concept.strip()

    concepts.append(concept)
    await llm.emit_message(f'- {concept}\n')
    await llm.emit_listener_event('boost.concept', {'concept': concept})
    await short_pause()

  await llm.emit_message('\n### Strategies\n')
  strategies = []

  for _ in range(cfg.strategies):
    strategy = await llm.chat_completion(
      prompt=strategies_prompt,
      conversation=chat,
      concepts=', '.join(strategies) if strategies else 'No strategies yet',
      params=exploration_params,
      resolve=True,
    )
    strategy = strategy.strip()

    strategies.append(strategy)
    await llm.emit_listener_event('boost.concept', {'concept': strategy})
    await llm.emit_message(f'- {strategy}\n')
    await short_pause()

  await llm.emit_message('\n### Topics\n')
  topics = []

  for _ in range(cfg.topics):
    topic = await llm.chat_completion(
      prompt=topics_prompt,
      conversation=chat,
      concepts=', '.join(topics) if topics else 'No topics yet',
      params=exploration_params,
      resolve=True,
    )
    topic = topic.strip()

    topics.append(topic)
    await llm.emit_listener_event('boost.concept', {'concept': topic})
    await llm.emit_message(f'- {topic}\n')
    await short_pause()

  await llm.emit_message('\n### Linking concepts\n')
  everything = concepts + strategies + topics
  links = []

  for _ in range(cfg.links):

    class PickNextSchema(BaseModel):
      concept: str = Field(
        description='List of two concepts that are picked from the list.',
        min_items=2,
        max_items=2,
      )

      model_config = {
        "json_schema_extra":
          {
            "properties": {
              "concept": {
                "type": "string",
                "enum": everything
              }
            }
          }
      }

    pick_response = await llm.chat_completion(
      prompt=pick_next_concept_schema,
      conversation=chat,
      concepts='\n'.join(everything),
      params=exploration_params,
      schema=PickNextSchema,
      resolve=True,
    )

    picked_concept = pick_response['concept']
    links += [picked_concept]
    everything.remove(picked_concept)

    if len(links) > 1:
      await llm.emit_listener_event(
        'boost.linked_concepts', {'concepts': [links[-2], links[-1]]}
      )
      await llm.emit_message(f'- {links[-2]} -> {links[-1]}\n')

  await llm.stop_thinking()

  response_plan = '\n - ' + ('\n - '.join(links))
  await llm.stream_final_completion(
    prompt=follow_plan_prompt,
    conversation=chat,
    plan=response_plan,
  )
