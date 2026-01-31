import asyncio
import traceback

from llm import LLM
from log import setup_logger

import tasks.next_step as next_step
import tasks.plan as plan
import tasks.chat_to_goal as chat_to_goal

logger = setup_logger(__name__)

class Agent:
  llm: LLM

  def __init__(self, llm: LLM):
    self.llm = llm

  async def serve(self):
    async def execute():
      try:
        await self.execute()
      except Exception as e:
        logger.error(f"Failed to execute: {e}")
        for line in traceback.format_tb(e.__traceback__):
          logger.error(line)

      # Emit Done is necessary at the end, no matter what
      logger.debug(f"Execution complete")
      await self.llm.emit_done()

    # Launch execution, and return the response stream
    asyncio.create_task(execute())
    return self.llm.response_stream()

  async def execute(self):
    logger.debug('Converting chat to goal')
    goal_response = await chat_to_goal.execute(self.llm, self.llm.chat)
    logger.debug(f"Iteration goal: {goal_response}")

    plan_response = await plan.execute(
      llm=self.llm,
      objective=goal_response['goal']
    )

    logger.debug(f"Plan: {plan_response}")

    await self.llm.stream_final_completion(
      prompt="""
        Outline how a given plan will accomplish the objective.

        Plan:
        {plan}

        Objective:
        {objective}
      """.strip(),
      plan=plan_response['steps'],
      objective=goal_response['goal']
    )