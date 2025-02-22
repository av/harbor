import asyncio
import chat as ch
import llm
import os

ID_PREFIX='webui_artifact'

current_dir = os.path.dirname(os.path.abspath(__file__))
artifact_path = os.path.join(current_dir, 'artifacts', 'tokens_mini.html')

with open(artifact_path, 'r') as file:
  artifact = file.read()

async def apply(chat: 'ch.Chat', llm: 'llm.LLM'):
  await llm.emit_artifact(artifact.replace('<<listener_id>>', llm.id))
  await asyncio.sleep(0.1)

  await llm.stream_final_completion()