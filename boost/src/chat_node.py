import random

from typing import List, Optional
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

  def add_parent(self, parent: 'ChatNode'):
    parent.children.append(self)
    self.parent = parent
    return self

  def add_child(self, child: 'ChatNode'):
    child.parent = self
    self.children.append(child)
    return child

  def best_child(self):
    if not self.children:
      return self
    return max(self.children, key=lambda c: c.value).best_child()

  def contains(self, substring):
    return substring.lower() in self.content.lower()

  def parents(self):
    parents = [self]

    while self.parent:
      self = self.parent
      parents.append(self)

    return parents[::-1]

  def message(self):
    return {
      "role": self.role,
      "content": self.content,
    }

  def ancestor(self):
    node = self
    while node.parent:
      node = node.parent
    return node

  def history(self):
    node = self
    messages = [node.message()]

    while node.parent:
      node = node.parent
      messages.append(node.message())

    return messages[::-1]

  def __str__(self):
    return f"{self.role}: {self.content}"
