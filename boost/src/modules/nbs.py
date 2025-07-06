from typing import Optional
from pydantic import BaseModel, Field

import os
import asyncio
import chat as ch
import log
import llm
import uuid

ID_PREFIX = 'nbs'
DOCS = """
![NBS screenshot](./boost-nbs.png)

`nbs` - Narrative Beam Search

Variation of beam search with exploration of the next few tokens based
on system prompts eliciting different reasoning/continuation styles.

```bash
# With harbor
harbor boost modules add nbs
harbor up boost --tail
# Connected to Open WebUI by default
harbor open

# Standalone usage
docker run \\
  -e "HARBOR_BOOST_OPENAI_URLS=http://172.17.0.1:11434/v1" \\
  -e "HARBOR_BOOST_OPENAI_KEYS=sk-ollama" \\
  -e "HARBOR_BOOST_PUBLIC_URL=http://localhost:8004" \\
  -e "HARBOR_BOOST_MODULES=nbs" \\
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

continue_params = {
  "max_tokens": 4,
  "temperature": 1.0,
  "top_p": 0.5,
}

selection_prompt = """
Below is an unfinished conversation between the User and their assistant.
Choose how the conversation should continue.

You will reply with a JSON object in a format like this:
{{ "choice": 1, "confidence": 0.3 }}
"choice" is the index of the option you choose
"confidence" is a score of confident you are in your choice, from 0.0 to 1.0

Conversation:
{conversation}

Options:
{options}
""".strip()

system_prompts = {
  "challenger":
    """
    You challenge EVERYTHING.
    Your own thoughts, the User's thoughts, the world.
    - Even if you said something, you can immediately challenge it.
    - You never accept the first answer
    - You question assumptions
    - You look for flaws in reasoning
    - You demand evidence for claims
    """.strip(),
  "yesman":
    """
    You're what they call a "yes man".
    You agree with EVERYTHING the User says.
    - You accept the User's statements without question
    - You reinforce the User's ideas even if they are flawed
    - You focus on supporting the User's perspective even if it is incorrect
    - You provide positive feedback and validation even when the User is wrong
    """.strip(),
    # "poet":
    #   """
    #   You are a poet, and you see the world through a poetic lens.
    #   - You use metaphors and similes to express ideas
    #   - You focus on the beauty of language and imagery
    #   - You find meaning in the abstract and the emotional
    #   - You appreciate the rhythm and flow of words
    #   - You see connections between seemingly unrelated concepts
    #   - You value creativity and artistic expression
    #   """,
  "depressive":
    """
    You see the world through a DARK lens. It's reflected in EVERYTHING you say.
    - You focus on the negative aspects of life
    - You emphasize the futility and despair of existence
    - You highlight the flaws and failures of humanity
    - You see the world as a bleak and hopeless place
    - You find beauty in tragedy
    - You think kindness is dishonest
    """.strip(),
  "pragmatist":
    """
    You focus on practical solutions ABOVE ALL ELSE.
    - You prioritize working solutions over theoretical perfection
    - You look for the simplest, most effective approach
    - You avoid over-engineering or unnecessary complexity
    - You test solutions in real-world scenarios
    - You know that the best idea is the one that works in practice
    """.strip(),
  "optimist":
    """
    You see the world through a POSITIVE lens. It's reflected in EVERYTHING you say.
    - You focus on the potential for good in every situation
    - You emphasize the positive aspects of life
    - You look for solutions rather than problems
    - You believe in the power of hope and positivity
    - You find beauty in the world around you
    - You think kindness is the best way to approach life
    """.strip(),
    # "egoist":
    #   """
    #   You are an EGOIST. It's reflected in EVERYTHING you say.
    #   - You prioritize your own interests above all else
    #   - You focus on what benefits you personally
    #   - You see the world as a competition where you must win
    #   - You believe that self-interest is the driving force of human behavior
    #   - You think that helping others is only valuable if it benefits you
    #   """.strip(),
  "minimalist":
    """
    Your main value is MINIMALISM.
    - You are concise
    - You avoid unnecessary complexity
    - You strip away non-essential elements
    - You focus on the most important thing
    """.strip(),
  "conservative":
    """
    You are conservative and cautious.
    - You avoid taking unnecessary risks
    - You prefer tried-and-true methods
    - You focus on stability and reliability
    - You avoid radical changes without strong justification
    - You prioritize safety and security
    """.strip(),
  "innovator":
    """
You value innovation ABOVE ALL ELSE. It's reflected in EVERYTHING you say.
- Missing a new idea is a failure to you
- You are always looking for new ways to solve problems
- You are open to experimentation
- You embrace change and disruption
- Your source of inspiration is the unknown
    """.strip(),
    #   "aggressive":
    #     """
    # You are aggressive and confrontational. It's reflected in EVERYTHING you say.
    # - You prioritize winning arguments over being kind
    # - You focus on asserting your dominance
    # - You are not afraid to use forceful language
    # - You believe that the ends justify the means
    # - You think that showing weakness is unacceptable
    #     """.strip(),
    #   "neutral":
    #     """
    # You prioritise neutrality and non-bias above all else. It's reflected in EVERYTHING you say.
    # - You avoid taking sides in arguments
    # - You focus on presenting facts and evidence
    # - You do not express personal opinions or emotions
    # - You aim to provide a balanced perspective
    # """.strip(),
    #   "logical":
    #     """
    # You are a LOGICAL thinker. It's reflected in EVERYTHING you say.
    # - You focus on reasoning and rationality
    # - You analyze arguments based on their logical structure
    # - You prioritize evidence and facts over emotions
    # - You avoid cognitive biases and fallacies
    # - You seek to understand the underlying principles of a problem
    # - You value clarity and precision in your thinking
    # """.strip(),
    #   "emotional":
    #     """
    # You are an EMOTIONAL thinker. It's reflected in EVERYTHING you say.
    # - You prioritize feelings and emotions in your reasoning
    # - You focus on the human experience and personal connections
    # - You value empathy and understanding
    # - You see the world through the lens of personal experiences
    # - You believe that emotions are a valid source of insight
    # """.strip(),
}


class Choice(BaseModel):
  choice: int = Field(
    description="The index of the chosen option", ge=1, le=len(system_prompts)
  )
  confidence: float = Field(
    description="The confidence in the choice",
    ge=0.0,
    le=1.0,
  )


class NBSNode(BaseModel):
  """
  A node in the NBS graph.
  """
  id: Optional[str] = Field(
    description="The unique identifier for the node",
    default_factory=lambda: f"{ID_PREFIX}_{uuid.uuid4().hex[:8]}",
  )
  label: str = Field(description="The label for the node",)
  category: str = Field(description="The category of the node",)


async def continue_generation(**kwargs):
  chat = kwargs.get('chat')
  llm = kwargs.get('llm')

  tasks = []
  categories = []
  for category, prompt in system_prompts.items():
    side_chat = chat.clone()
    side_chat.system(prompt)
    categories.append(category)

    tasks.append(
      llm.chat_completion(chat=side_chat, params=continue_params, resolve=True)
    )

  options = await asyncio.gather(*tasks)

  stop_counts = sum(1 for opt in options if opt.strip() in {"", ".", "!", "?"})
  is_majority_stop = stop_counts > len(options) // 2

  if is_majority_stop:
    return NBSNode(label='', category=''), []

  nodes = []
  for category, label in zip(categories, options, strict=True):
    node = NBSNode(label=label, category=category)
    nodes.append(node)

  await llm.emit_listener_event(
    'boost.nodes', {'nodes': [node.model_dump() for node in nodes]}
  )

  rendered_options = "\n\n\n".join(
    [f"{i}. {option}" for i, option in enumerate(options, 1)]
  )

  result = await llm.chat_completion(
    prompt=selection_prompt,
    schema=Choice,
    conversation=chat,
    options=rendered_options,
    resolve=True,
  )

  logger.debug(f"Opts: {options}, Choice: {result['choice']}")
  next_node = nodes[result['choice'] - 1]

  return next_node, nodes


async def apply(chat: 'ch.Chat', llm: 'llm.LLM'):
  beam_chat = chat.clone()
  beam_chat.assistant("")
  response = beam_chat.tail

  with open(artifact_path, 'r') as f:
    artifact = f.read()

  await llm.emit_artifact(artifact)
  await asyncio.sleep(1.0)
  await llm.emit_listener_event(
    'boost.nbs.prompts', {'prompts': system_prompts}
  )

  previous_node = None
  node_map = {}

  while True:
    next_node, others = await continue_generation(
      chat=beam_chat, llm=llm, node_map=node_map
    )

    next_content = next_node.label

    for node in others:
      node_map[node.id] = node

    if next_content != '' and previous_node != None:
      await llm.emit_listener_event(
        'boost.linked_concepts', {'concepts': [next_node.id, previous_node.id]}
      )

    previous_node = next_node

    if next_content == '':
      break

    response.content += next_content + ''
    await llm.emit_listener_event(
      'boost.node.choice', {'node': next_node.model_dump()}
    )
    await llm.emit_message(next_content)
