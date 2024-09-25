# Recursive Certainty Validation - RCN
# aka "Are you sure?

import re
from typing import Optional, List
from config import MCTS_STRAT, MCTS_STRAT_PARAMS, MCTS_EXPLORATION_CONSTANT, MCTS_MAX_SIMULATIONS, MCTS_MAX_ITERATIONS, MCTS_THOUGHTS

import llm
import log
import random
import math
import chat as ch
import selection

# ==============================================================================

logger = log.setup_logger(__name__)
ID_PREFIX = "mcts"

# ==============================================================================

thoughts_prompt = """
<instruction>
Give a suggestion on how this answer can be improved.
WRITE ONLY AN IMPROVEMENT SUGGESTION AND NOTHING ELSE.
YOUR REPLY SHOULD BE A SINGLE SENTENCE.
</instruction>

<question>
{question}
</question>

<draft>
{answer}
</draft>
""".strip()

eval_answer_prompt = """
Given the following text:
"{answer}"

How well does it answers this question:
"{question}"

Rate the answer from 1 to 10, where 1 is completely wrong or irrelevant and 10 is a perfect answer.
Reply with a single number between 1 and 10 only. Do not write anything else, it will be discarded.
THINK CAREFULLY AND USE BEST PRACTICES.
""".strip()

analyze_prompt = """
Iteration Analysis:

Original question: {question}
Best answer found: {best_answer}
Best score achieved: {best_score}

Analyze this iteration of the thought process. Consider the following:
1. What aspects of the best answer made it successful?
2. What patterns or approaches led to higher-scoring thoughts?
3. Were there any common pitfalls or irrelevant tangents in lower-scoring thoughts?
4. How can the thought generation process be improved for the next iteration?

Provide a concise analysis and suggest one specific improvement strategy for the next iteration.
""".strip()

update_prompt = """
<instruction>
Your task is to read the question and the answer below, then analyse the given critique.
When you are done - think about how the answer can be improved based on the critique.
WRITE A REVISED ANSWER THAT ADDRESSES THE CRITIQUE. DO NOT WRITE ANYTHING ELSE.
</instruction>
<question>
{question}
</question>
<draft>
{answer}
</draft>
<critique>
{improvements}
</critique>
""".strip()

initial_prompt = """
<instruction>
Answer the question below. Do not pay attention to, unexpected casing, punctuation or accent marks.
</instruction>

<question>
{question}
</question>
"""


class MCTSNode(ch.ChatNode):
  children: List['MCTSNode']
  exploration_weight: float
  max_children = 2

  def fully_expanded(self):
    return len(self.children) >= self.max_children

  def uct_value(self):
    epsilon = 1e-6

    return self.value / (self.visits +
                         epsilon) + self.exploration_weight * math.sqrt(
                           math.log(self.parent.visits) /
                           (self.visits + epsilon)
                         )

  def mermaid(self, offset=0, selected=None):
    padding = " " * offset
    msg = f"{padding}{self.id}({self.id}:{self.visits} - {escape_mermaid(self.content[:25])})\n"

    if selected == self.id:
      msg += f"{padding}style {self.id} stroke:#0ff\n"

    for child in self.children:
      msg += child.mermaid(offset + 4, selected)
      msg += f"{padding}{self.id} --> {child.id}\n"

    return msg


class MCTS:
  question: str
  root: MCTSNode
  llm: 'llm.LLM'
  selected: Optional['ch.ChatNode']
  exploration_weight: float
  thoughts: int

  def __init__(self, **kwargs):
    self.question = kwargs.get("question")
    self.root = kwargs.get("root")
    self.llm = kwargs.get("llm")
    self.selected = None
    self.exploration_weight = kwargs.get(
      "exploration_weight", MCTS_EXPLORATION_CONSTANT.value
    )
    self.thoughts = kwargs.get("thoughts", MCTS_THOUGHTS.value)

  async def select(self):
    logger.debug("Selecting node...")
    node = self.root
    while node.children:
      node = self.uct_select(node)
    return node

  async def expand(self, node):
    logger.debug(f"Expanding node {node.id}...")
    await self.llm.emit_status(f"Thinking about {node.id}...")

    for _ in range(random.randint(self.thoughts, self.thoughts + 1)):
      thought = await self.generate_thought(node.content)
      await self.llm.emit_message(f"\nThought: {thought}\n")
      new_content = await self.update_approach(node.content, thought)
      child = self.create_node(content=new_content, parent=node)
      node.add_child(child)

    return random.choice(node.children)

  async def simulate(self, node: MCTSNode):
    logger.debug(f"Simulating node {node.id}...")
    await self.llm.emit_status(f"Thinking about {node.id}...")
    await self.llm.emit_message(self.mermaid())
    return await self.evaluate_answer(node.content)

  def backpropagate(self, node: MCTSNode, score: float):
    logger.debug(f"Backpropagating from {node.id}...")
    while node:
      node.visits += 1
      node.value += score
      node = node.parent

  def uct_select(self, node: MCTSNode):
    logger.debug(f"Selecting uct {node.id}...")
    return max(node.children, key=lambda child: child.uct_value())

  def best_child(self):
    return self.root.best_child()

  async def search(self, num_simulations):
    logger.debug("Starting search...")

    for _ in range(num_simulations):
      leaf = await self.select()
      self.selected = leaf
      if not leaf.fully_expanded():
        leaf = await self.expand(leaf)
      score = await self.simulate(leaf)
      self.backpropagate(leaf, score)

    return self.selected

  def create_node(self, **kwargs):
    node = MCTSNode(**kwargs)
    node.exploration_weight = self.exploration_weight

    return node

  async def generate_thought(self, answer):
    return await self.llm.chat_completion(
      prompt=thoughts_prompt,
      answer=answer,
      question=self.question,
      resolve=True
    )

  async def analyze_iteration(self, best_answer, best_score):
    return await self.llm.chat_completion(
      prompt=analyze_prompt,
      question=self.question,
      best_answer=best_answer,
      best_score=best_score,
      resolve=True
    )

  async def update_approach(self, answer, improvements):
    return await self.llm.chat_completion(
      prompt=update_prompt,
      question=self.question,
      answer=answer,
      improvements=improvements,
      resolve=True,
    )

  async def evaluate_answer(self, answer):
    result = await self.llm.chat_completion(
      prompt=eval_answer_prompt,
      answer=answer,
      question=self.question,
      resolve=True,
    )

    try:
      score = re.search(r"\d+", result).group()
      return int(score)
    except AttributeError:
      logger.error(f"AnswerEval: unable to parse \"{result[:100]}\"")
      return 0

  def mermaid(self, selected=None):
    return f"""
```mermaid
graph LR
{self.root.mermaid(0, selected.id if selected else self.selected.id)}
```
"""


def escape_mermaid(text):
  return text.replace('"', "&quot;").replace("(", "&#40;").replace(")", "&#41;")


# ==============================================================================
async def apply(chat: 'ch.Chat', llm: 'llm.LLM'):
  strat = MCTS_STRAT.value
  strat_params = MCTS_STRAT_PARAMS.value
  exploration_constant = MCTS_EXPLORATION_CONSTANT.value
  max_simulations = MCTS_MAX_SIMULATIONS.value
  max_iterations = MCTS_MAX_ITERATIONS.value
  thoughts = MCTS_THOUGHTS.value

  debug_info = {
    "strat": strat,
    "strat_params": strat_params,
    "exploration_constant": exploration_constant,
    "max_simulations": max_simulations,
    "max_iterations": max_iterations,
    "thoughts": thoughts,
  }

  logger.debug(f"{ID_PREFIX}: {debug_info}")
  nodes = selection.apply_strategy(chat, strategy=strat, params=strat_params)

  if (len(nodes) > 1):
    logger.warning(
      f"{ID_PREFIX}: Matched multiple nodes, only the first one will be processed."
    )

  if len(nodes) == 0:
    log.info(f"{ID_PREFIX}: No nodes matched, skipping.")
    return llm.stream_chat_completion()

  node = nodes[0]
  question = node.content

  await llm.emit_status('Preparing initial thoughts...')
  mcts_chat = ch.Chat(
    llm=llm,
    tail=MCTSNode(
      role="user", content=initial_prompt.format(question=question)
    )
  )
  mcts_chat.chat_node_type = MCTSNode
  mcts_chat.llm = llm
  await mcts_chat.emit_advance()

  await llm.emit_status('Starting MCTS search...')
  mcts = MCTS(
    question=question,
    root=mcts_chat.tail,
    llm=llm,
    exploration_weight=exploration_constant,
    thoughts=thoughts
  )

  best_answer = None
  best_score = -float("inf")

  for i in range(max_iterations):
    await llm.emit_status(f"MCTS iteration {i + 1}/{max_iterations}...")
    best_node = await mcts.search(max_simulations)
    score = await mcts.evaluate_answer(best_node.content)

    if score > best_score:
      best_answer = best_node.content
      best_score = score

  # Final completion
  mcts_chat.assistant(f"Here is the best answer I can think of: {best_answer}")
  mcts_chat.user('Thank you, now please summarize it for me.')
  await llm.stream_final_completion(chat=mcts_chat)
