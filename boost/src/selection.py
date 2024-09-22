import random

from chat import Chat

def percentage(chat: Chat, **kwargs):
  percentage = kwargs.get("percentage", 50)
  nodes = chat.plain()
  num_nodes = max(1, int(len(nodes) * (percentage / 100)))

  return nodes[:num_nodes]

def match(chat: Chat, **kwargs):
  substring = kwargs.get("substring", "")
  role = kwargs.get("role", "")
  index = kwargs.get("index", None)

  nodes = chat.plain()

  if role:
    nodes = [node for node in nodes if node.role == role]

  if substring:
    nodes = [node for node in nodes if substring in node.content]

  if index is not None:
    nodes = [nodes[index]]

  return nodes

def user(chat: Chat):
  return match(chat, role="user")

def all(chat: Chat):
  return chat.plain()

def first(chat: Chat):
  return match(chat, index=0)

def last(chat: Chat):
  return match(chat, index=-1)

def any(chat: Chat):
  return [random.choice(chat.plain())]


selection_strategies = {
  "all": all,
  "first": first,
  "last": last,
  "any": any,
  "percentage": percentage,
  "match": match,
  "user": user,
}

def apply_selection_strategy(chat: Chat, strategy: str, params: dict):
  return selection_strategies[strategy](chat, **params)