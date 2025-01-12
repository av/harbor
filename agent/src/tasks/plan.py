from pydantic import BaseModel, Field
from typing import List

from llm import LLM

class Step(BaseModel):
  explanation: str = Field(description = "3-5 words explaining your reasoning")
  action: str = Field(description = "The action to take")

class Plan(BaseModel):
  steps: List[Step] = Field(description = "A list of steps to take")

plan_prompt = """
Write a plan of actions to achieve the objective using a computer.
The plan must be detailed and clear, it'll be given to someone barely familiar with the subject.
When objective is unrelated to computer use - reply with a single step explaining how to achieve it.

Objective:
{objective}

Reply with a JSON object following given JSON schema to the letter.
{response_schema}
""".strip()

async def execute(llm: LLM, objective: str):
  result = await llm.chat_completion(
    prompt=plan_prompt,
    schema=Plan,
    objective=objective,
    response_schema=Plan.schema_json(indent=2),
    resolve=True
  )

  return result
