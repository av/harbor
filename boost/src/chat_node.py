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
      child = ChatNode(role=message['role'], content=message['content'])
      node.add_child(child)
      node = child

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

  def add_parent(self, new_parent: 'ChatNode'):
    # Guard against None and self-reference
    if new_parent is None or self == new_parent:
      return self

    # Remove from current parent if exists
    if self.parent:
      self.parent.children.remove(self)

    # Set new parent
    self.parent = new_parent
    if self not in new_parent.children:
      new_parent.children.append(self)

    return self

  # add child - similar to adding another branch
  # to the conversation from this node
  def add_child(self, child: 'ChatNode'):
    # Guard against None and duplicates
    if child is None or child in self.children:
      return self

    for c in self.children:
      c.add_parent(child)

    # Update child's parent
    if child.parent:
      child.parent.children.remove(child)
    child.parent = self

    # Add to children
    self.children.append(child)
    return self

  # insert child - similar to adding a new node
  # in the middle of the conversation
  def insert_child(self, child: 'ChatNode'):
    self.add_child(child)
    for c in self.children:
      c.add_parent(child)
    return self

  def remove_child(self, child: 'ChatNode'):
    if child in self.children:
      self.children.remove(child)
      child.parent = None
    return self

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
