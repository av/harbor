from pydantic import BaseModel, Field
from typing import List

from llm import LLM

class Refiner(BaseModel):
  explanation: str = Field(description = "One short sentence explaining what you have done")
  content: str = Field(description = "The content refined according to the instruction")

plan_prompt = """
Below is the content that needs to be refined and the instruction on how to do that.
Refine the content according to the instruction.

Instruction:
{instruction}

Content:
{content}
""".strip()

async def execute(llm: LLM, content: str, instruction: str):
  result = await llm.chat_completion(
    prompt=plan_prompt,
    schema=Refiner,
    instruction=instruction,
    content=content,
    resolve=True
  )

  return result
