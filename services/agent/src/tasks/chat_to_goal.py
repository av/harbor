from pydantic import BaseModel, Field

from chat import Chat
from chat_node import ChatNode
from llm import LLM
from log import setup_logger

logger = setup_logger(__name__)

class ChatToGoal(BaseModel):
  explanation: str = Field(description = "One very short sentence explaining your reasoning")
  goal: str = Field(description = "The next immediate goal of the user")

chat_to_goal_prompt = """
Given a past conversation between you and the user, analyze it to:
1. Identify the user's immediate next objective
2. Rephrase it as a direct instruction from the user to you

Reply with a JSON object following this schema to the letter:
{response_schema}

Conversation:
{goal_chat}
""".strip()

async def execute(llm: LLM, chat: Chat):
  # Small LLMs behave better with this tiny fake conversation to start with
  if len(chat.history()) == 1:
    chat = Chat.from_conversation([
      {
        "role": "user",
        "content": "Hi"
      },
      {
        "role": "assistant",
        "content": "Hello! How can I help you today?"
      },
      {
        "role": chat.tail.role,
        "content": chat.tail.content
      }
    ])

  response = await llm.chat_completion(
    prompt=chat_to_goal_prompt,
    goal_chat=chat,
    response_schema=ChatToGoal.model_json_schema(),
    schema=ChatToGoal,
    resolve=True
  )

  return response