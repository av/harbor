from typing import Optional

from chat_node import ChatNode
import llm
import log

logger = log.setup_logger(__name__)


class Chat:
  tail: ChatNode
  llm: Optional['llm.LLM']

  def from_conversation(messages):
    tail = ChatNode.from_conversation(messages)
    return Chat(tail=tail)

  def from_tail(chat):
    new_tail = ChatNode(role=chat.tail.role, content=chat.tail.content)
    return Chat(tail=new_tail)

  def __init__(self, **kwargs):
    self.tail = kwargs.get('tail')
    self.llm = kwargs.get('llm')
    self.chat_node_type = ChatNode

    self.Chat = Chat
    self.ChatNode = self.chat_node_type

  def has_substring(self, substring):
    return any(substring in msg.content for msg in self.plain())

  def add_message(self, role, content):
    logger.debug(f"Chat message: {role}: {content[:50]}")

    self.tail = self.tail.add_child(
      self.__create_node(role=role, content=content)
    )
    return self.tail

  def user(self, content):
    return self.add_message('user', content)

  def assistant(self, content):
    return self.add_message('assistant', content)

  def system(self, content):
    return self.add_message('system', content)

  def plain(self):
    return self.tail.parents()

  def history(self):
    return self.tail.history()

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

  async def emit_advance(self):
    """
    Emit the next step in the chat completion

    Will be streamed back to the client
    """

    if not self.llm:
      raise ValueError("Chat: unable to advance without an LLM")

    response = await self.llm.stream_chat_completion(chat=self)
    self.assistant(response)

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
