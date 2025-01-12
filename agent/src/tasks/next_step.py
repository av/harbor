from pydantic import BaseModel, Field
from enum import Enum

from llm import LLM

class StepType(str, Enum):
  ACTION = 'action'

class NextStep(BaseModel):
  explanation: str = Field(description = "One short sentence explaining your reasoning")
  type: StepType = Field(description = "The type of step to take")

next_action_prompt = """
Plan an immediate next step to to advance current state towards the final goal.

Current state:
{current_state}

Final goal:
{final_goal}
""".strip()

async def execute(llm: LLM, goal: str):
  result = await llm.chat_completion(
    prompt=next_action_prompt,
    schema=NextStep,
    final_goal=goal,
    current_state='Nothing is done yet',
    resolve=True
  )

  return result
