from pydantic import BaseModel, Field

import asyncio

import os

import log
import chat as ch
import llm

ID_PREFIX = 'concept'
DOCS = """
![concept](./boost-concept.png)

`concept` is a module allowing LLM to first generate a small concept graph to aid it in replying to the original message.
The entire workflow is completely orchestrated so less interesting from interpretability perspective, but more from the representation perspective.

```bash
# With Harbor
harbor boost modules add concept

# Standalone usage
docker run \\
  -e "HARBOR_BOOST_OPENAI_URLS=http://172.17.0.1:11434/v1" \\
  -e "HARBOR_BOOST_OPENAI_KEYS=sk-ollama" \\
  -e "HARBOR_BOOST_PUBLIC_URL=http://localhost:8004" \\
  -e "HARBOR_BOOST_MODULES=concept" \\
  -p 8004:8000 \
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
    # Dev
    # 'fluid',
    # 'dist',
    # 'fluid_built.html',
    # Built
  'fluid_mini.html',
)

concept_explanation = """
Concepts are short pieces of information (1-3 words) that are relevant to the message.
They can be topics, emotions, intents, or content types.
The goal is to identify the most important concepts in the message and provide a concise description of each concept.
Concept color must be gray, except for the concepts identifying the strongest emotions.
"""

concepts_prompt = """
Suggest a list of ten concepts that are relevant to the conversation below and cover:
- Message's:
  - Content
  - Emotional tone
  - Intent
- Possible reply's:
  - Content
  - Emotional tone
  - Intent

Message:
{message}

Reply with a JSON object with a single field "concepts" that contains an array of concepts.
{concept_explanation}
""".format(
  message='{message}',
  concept_explanation=concept_explanation,
)

related_concept_prompt = """
Suggest a concept that is related to the given one in the context of a given message.
The concept should be 2-3 words long, unique and relevant to both the message and the given concept.
It can be a topic, an emotion, an intent, knowledge, reaction, thought - anything, just make sure it is relevant and concise.

Message:
{message}

Concept:
{concept}

Reply with a JSON object describing the concept with the following fields (label, hex_color).
{concept_explanation}
""".format(
  message='{message}',
  concept='{concept}',
  concept_explanation=concept_explanation,
)

consider_concept_prompt = """
Please consider the following concept in the context of the message below.
Reply with a single short sentence describing the implications of this concept for the message.

Message:
{message}

Concept:
{concept}
"""

completion_prompt = """
Consider below concept graph in your reply.
Do not mention it explicitly, but use it as a context for your response.

Concept graph (links between concepts):
{concept_graph}
"""


class ConceptSchema(BaseModel):
  label: str = Field(
    description="""
    One to three words that describe the concept.
    The concept can be a topic, an emotion, an intent, or a content type.
    It can really be anything that is relevant to the message, but it should be concise and specific.
    """,
  )
  hex_color: str = Field(
    description="""
    A valid HEX color that is associated with the concept.
    Must be gray for anything but the strongest emotions.
    """,
    default='#010101',
  )

  def normalize_label(self):
    """
    Normalize to Title Case to refer to the concept in a human-readable way.
    """
    self.label = self.label.title()


class ConsiderationSchema(BaseModel):
  consideration: str = Field(
    description="""
    A short sentence describing the implications of this concept for the message.
    It should be concise and specific, and should help to understand how the concept relates to the message.
    """
  )


class ConceptOutputSchema(BaseModel):
  concepts: list[ConceptSchema] = Field(
    description='List of concepts that are relevant to the message.',
    min_items=1,
    max_items=10,
  )


async def apply(chat: 'ch.Chat', llm: 'llm.LLM'):
  with open(artifact_path, 'r') as f:
    artifact = f.read()

  if 'qwen3' in llm.model:
    chat.system('/no_think')

  await llm.emit_artifact(artifact=artifact)
  await llm.emit_listener_event('boost.status', {'status': 'Initializing'})
  await llm.emit_listener_event('boost.intensity', {'intensity': 1.0})

  await llm.start_thinking()
  await llm.emit_message('\n### Concepts\n')
  concepts = set()
  links = set()
  context = {}

  raw_output = await llm.chat_completion(
    prompt=concepts_prompt,
    message=chat.tail.content,
    schema=ConceptOutputSchema,
    resolve=True,
  )
  output = ConceptOutputSchema(**raw_output)

  await llm.emit_listener_event('boost.intensity', {'intensity': 0.4})
  await llm.emit_listener_event('boost.status', {'status': 'Thinking'})

  logger.error(f'Output: {output}')

  async def add_concept(concept: ConceptSchema):
    concept.normalize_label()
    await llm.emit_listener_event('boost.concept', concept.model_dump())
    await llm.emit_message(f'- {concept.label} ({concept.hex_color})\n')

    if not concept.label in context:
      consideration_response = await llm.chat_completion(
        prompt=consider_concept_prompt,
        message=chat.tail.content,
        concept=concept.label,
        schema=ConsiderationSchema,
        resolve=True,
      )
      consideration = ConsiderationSchema(**consideration_response)
      context[concept.label] = consideration.consideration

    concepts.add(concept.label)

  for concept in output.concepts:
    await add_concept(concept)

  for _ in range(3):
    for concept in output.concepts:
      await llm.emit_listener_event(
        'boost.status', {'status': f'Thinking about "{concept.label}"'}
      )
      raw_output = await llm.chat_completion(
        prompt=related_concept_prompt,
        message=chat.tail.content,
        concept=concept.label,
        schema=ConceptSchema,
        resolve=True,
      )
      related_concept = ConceptSchema(**raw_output)
      await add_concept(related_concept)
      links.add((concept.label, related_concept.label))

      await llm.emit_listener_event(
        'boost.linked_concepts', {
          'concepts': [concept.label, related_concept.label],
        }
      )

  await llm.emit_listener_event('boost.status', {'status': 'Done'})

  await llm.emit_message('\n### Concept Graph\n')
  logger.error(f'Concepts: {context}')
  concept_graph = ''
  for concept in context:
    related = [
      c for c in concepts if (concept, c) in links or (c, concept) in links
    ]
    concept_graph += f'### {concept}\n{context[concept]}\nRelated: {", ".join(related)}\n\n'
  llm.chat.system(completion_prompt.format(concept_graph=concept_graph,))
  await llm.emit_message(concept_graph)

  await llm.stop_thinking()
  await llm.stream_final_completion(
    prompt="""
Reply to the conversation below based on the context.

# Context
{context}

# Conversation
{conversation}

Reply with next message in the conversation from the perspective of the assistant.
""",
    context=concept_graph,
    conversation=chat,
  )
