import asyncio
import chat as ch
import llm
import os

ID_PREFIX='markov'

current_dir = os.path.dirname(os.path.abspath(__file__))
artifact_path = os.path.join(current_dir, '..', 'custom_modules', 'artifacts', 'graph_mini.html')

async def apply(chat: 'ch.Chat', llm: 'llm.LLM'):
  with open(artifact_path, 'r') as file:
    artifact = file.read()

  await llm.emit_artifact(artifact.replace('<<listener_id>>', llm.id))
  # Wait for the artifact to be loaded and
  # ready to accept messages
  await asyncio.sleep(1.0)
  await llm.stream_final_completion()