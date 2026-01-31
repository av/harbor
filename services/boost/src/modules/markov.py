import asyncio
import chat as ch
import llm
import os

ID_PREFIX = 'markov'
DOCS = """
![screenshot of markov module in action](./boost-markov.png)

⚠️ This module is only compatible with Open WebUI as a client due to its support of custom artifacts.

When serving LLM completion, it'll emit an artifact for Open WebUI that'll connect back to the Harbor Boost server and display emitted tokens in a graph where each token is connected to the one preceding it.

```bash
# Enable the module
harbor boost modules add markov
```
"""

current_dir = os.path.dirname(os.path.abspath(__file__))
artifact_path = os.path.join(
  current_dir, '..', 'custom_modules', 'artifacts', 'graph_mini.html'
)


async def apply(chat: 'ch.Chat', llm: 'llm.LLM'):
  with open(artifact_path, 'r') as file:
    artifact = file.read()

  await llm.emit_artifact(artifact)
  await llm.stream_final_completion()
