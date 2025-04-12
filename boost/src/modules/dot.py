from pydantic import BaseModel, Field

import asyncio
import os
import uuid

import log
import chat as ch
import llm

ID_PREFIX = "dot"

logger = log.setup_logger(ID_PREFIX)

current_dir = os.path.dirname(os.path.abspath(__file__))
artifact_path = os.path.join(
  current_dir, '..', 'custom_modules', 'artifacts', 'dot_mini.html'
)

class Step(BaseModel):
  id: str = Field(
    description="The unique identifier for the step.",
  )
  step: str = Field(
    description="The step of the reasoning process. Maximum 5 words.",
  )

class DraftPlan(BaseModel):
  steps: list[Step] = Field(
    description="The steps of the draft plan process.",
  )

draft_plan_prompt = """
<instruction>
Prepare a draft plan for addressing my query.

The plan is a list of steps, every step is a few words long and advances the reasoning process.
The plan does not jump to conclusions until the last step.
The plan step does not include any solutions or answers, only directions.
Plan accounts for possible ambiguities and uncertainties.
Good plan includes steps for self-checking and verification.

You will reply with a JSON object following this schema to the letter:
{response_schema}
</instruction>

<input name="query">
{message}
</input>
"""

execute_step_prompt = """
<instruction>
You are addresssing a query in a step-by-step manner.
Read the "query" and "past_steps" to understand where you are in the process.
Now, address the next portion of the plan listed in the "step".
</instruction>

<input name="query">
{query}
</input>

<input name="past_steps">
{past_steps}
</input>

<input name="step">
{step}
</input>
"""

summarise_draft_prompt = """
<instruction>
Assistant addressed user's query by creating and executing a step-by-step plan.
Your job is to rewrite assistant execution of the plan in a single coherent message.
Your response will be passed to the user instead of assistant's plan.
</instruction>

<input name="query">
{query}
</input>

<input name="execution">
{plan}
</input>
"""

async def serve_artifact(llm: 'llm.LLM'):
  with open(artifact_path, 'r') as file:
    artifact = file.read()

    await llm.emit_artifact(
      artifact
        .replace('<<listener_id>>', llm.id)
    )
    await asyncio.sleep(0.5)


async def apply(chat: 'ch.Chat', llm: 'llm.LLM'):
  logger.debug('sending artifact...')

  await serve_artifact(llm)
  await llm.emit_listener_event('dot.status', {
    'status': 'Drafting a plan',
  })

  plan_input = await llm.chat_completion(
    prompt=draft_plan_prompt,
    message=chat.tail.content,
    response_schema=DraftPlan.schema_json(indent=2),
    schema=DraftPlan,
    resolve=True,
  )
  plan = DraftPlan(**plan_input)

  for step in plan.steps:
    step.id = str(uuid.uuid4())[:8]
    await llm.emit_listener_event('dot.plan.step', step.__dict__)
    await asyncio.sleep(0.1)

  execution = []

  await llm.emit_listener_event('dot.status', {
    'status': 'Running',
  })

  for step in plan.steps:
    await llm.emit_listener_event('dot.step.status', {
      'id': step.id,
      'status': 'executing',
    })

    step_response = await llm.stream_chat_completion(
      prompt=execute_step_prompt,
      query=chat.tail.content,
      past_steps=[s.step for s in plan.steps],
      step=step.step,
      resolve=True,
      emit=False,
    )
    result = {
      "id": step.id,
      "response": step_response,
    }
    execution.append(result)
    await llm.emit_listener_event('dot.step.response', result)

  await llm.stream_final_completion(
    prompt=summarise_draft_prompt,
    query=chat.tail.content,
    plan=execution,
  )

  await llm.emit_listener_event('dot.status', {
    'status': 'Done',
  })


