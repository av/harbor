import random
import re

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


def apply_strategy(chat: Chat, strategy: str, params: dict):
  return selection_strategies[strategy](chat, **params)

def match_regex(value, regex):
  return bool(re.match(regex, value))

def match_substring(value, substring):
  return substring in value

def match_exact(value, target):
  return value == target

def matches_filter(obj: dict, filter: dict):
  for key in filter.keys():
    value = filter[key]
    field, operation = key.split('.') if '.' in key else (key, 'exact')

    if field not in obj:
      return False

    if operation == 'regex':
      return match_regex(str(obj[field]), value)
    elif operation == 'contains':
      return match_substring(str(obj[field]), value)
    else:
      return match_exact(str(obj[field]), value)

  return True