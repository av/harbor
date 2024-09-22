import random

from typing import List, Optional
import llm
import log

logger = log.setup_logger(__name__)

class ChatNode:
  id: str
  content: str
  role: str

  parent: Optional['ChatNode']
  children: List['ChatNode']

  visits: int
  value: float
  meta: dict

  def from_conversation(messages):
    root_message = messages[0]
    node = ChatNode(role=root_message['role'], content=root_message['content'])

    for message in messages[1:]:
      node = node.add_child(
        ChatNode(role=message['role'], content=message['content'])
      )

    return node

  def __init__(self, **kwargs):
    self.id = ''.join(
      random.choices('abcdefghijklmnopqrstuvwxyz0987654321', k=4)
    )
    self.content = kwargs.get('content', '')
    self.role = kwargs.get('role', '')

    self.parent = kwargs.get('parent', None)
    self.children = kwargs.get('children', [])

    self.visits = kwargs.get('visits', 0)
    self.value = kwargs.get('value', 0.0)

    self.meta = kwargs.get('meta', {})

  def add_child(self, child: 'ChatNode'):
    child.parent = self
    self.children.append(child)
    return child

  def best_child(self):
    if not self.children:
      return self
    return max(self.children, key=lambda c: c.value).best_child()

  def parents(self):
    parents = [self]

    while self.parent:
      self = self.parent
      parents.append(self)

    return parents[::-1]

  def history(self):
    node = self
    messages = [{
      "role": node.role,
      "content": node.content,
    }]

    while node.parent:
      node = node.parent
      messages.append({
        "role": node.role,
        "content": node.content,
      })

    return messages[::-1]

  def __str__(self):
    return f"{self.role}: {self.content}"


class Chat:
  tail: ChatNode
  llm: Optional['llm.LLM']

  def from_conversation(messages):
    tail = ChatNode.from_conversation(messages)
    return Chat(tail=tail)

  def __init__(self, **kwargs):
    self.tail = kwargs.get('tail')
    self.llm = kwargs.get('llm')

  def add_message(self, role, content):
    logger.debug(f"Chat message: {role}: {content[:50]}")

    self.tail = self.tail.add_child(ChatNode(role=role, content=content))
    return self.tail

  def user(self, content):
    return self.add_message('user', content)

  def assistant(self, content):
    return self.add_message('assistant', content)

  def plain(self):
    return self.tail.parents()

  def history(self):
    return self.tail.history()

  async def advance(self):
    if not self.llm:
      raise ValueError("Chat: unable to advance without an LLM")

    response = await self.llm.chat_completion(self)
    self.assistant(self.llm.get_response_content(response))

  def __str__(self):
    return '\n'.join([str(msg) for msg in self.parents()])
