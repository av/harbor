from typing import Optional

from chat_node import ChatNode
import llm
import log
import selection

logger = log.setup_logger(__name__)


class Chat:
  tail: ChatNode
  llm: Optional['llm.LLM']

  def from_conversation(messages):
    tail = ChatNode.from_conversation(messages)
    return Chat(tail=tail)

  def from_tail(chat: 'Chat'):
    new_tail = ChatNode(role=chat.tail.role, content=chat.tail.content)
    return Chat(tail=new_tail)

  def __init__(self, **kwargs):
    self.tail = kwargs.get('tail')
    self.llm = kwargs.get('llm')
    self.chat_node_type = ChatNode

    self.Chat = Chat
    self.ChatNode = self.chat_node_type

  def clone(self):
    return Chat.from_conversation(self.history())

  def has_substring(self, substring):
    return any(substring in msg.content for msg in self.plain())

  def match(self, **kwargs):
    return selection.match(self, **kwargs)

  def match_one(self, **kwargs):
    candidates = self.match(**kwargs)
    if not candidates:
      return None
    return candidates[0]

  def add_message(self, role, content):
    logger.debug(f"Chat message: {role}: {content[:50]}")

    child = self.__create_node(role=role, content=content)
    self.tail.add_child(child)
    self.tail = child

    return self.tail

  def user(self, content):
    return self.add_message('user', content)

  def assistant(self, content):
    return self.add_message('assistant', content)

  def system(self, content):
    self.tail.ancestor().add_parent(
      self.__create_node(role="system", content=content)
    )
    return self.tail

  def insert(self, after: ChatNode, role, content):
    new_node = self.__create_node(role=role, content=content)
    after.insert_child(new_node)

    if self.tail == after:
      self.tail = new_node

    return self.tail

  def plain(self):
    return self.tail.parents()

  def history(self):
    return self.tail.history()

  def root(self):
    return self.tail.ancestor()

  def text(self):
    # __str__ already does exactly this
    return f"{self}"

  def __create_node(self, **kwargs):
    NodeType = self.chat_node_type
    return NodeType(**kwargs)

  async def advance(self):
    """
    Advance the chat completion

    Will not be streamed back to the client
    """

    if not self.llm:
      raise ValueError("Chat: unable to advance without an LLM")

    response = await self.llm.chat_completion(chat=self)
    self.assistant(self.llm.get_response_content(response))
    return response

  async def emit_advance(self, **kwargs):
    """
    Emit the next step in the chat completion

    Will be streamed back to the client
    """

    if not self.llm:
      raise ValueError("Chat: unable to advance without an LLM")

    response = await self.llm.stream_chat_completion(chat=self, **kwargs)
    self.assistant(response)
    return response

  async def emit_status(self, status):
    """
    Emit a status message

    Will be streamed back to the client
    """

    if not self.llm:
      raise ValueError("Chat: unable to emit status without an LLM")

    await self.llm.emit_status(status)

  def __str__(self):
    return '\n'.join([str(msg) for msg in self.plain()])
