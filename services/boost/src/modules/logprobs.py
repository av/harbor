import os
import chat as ch
import llm as llm_module
import log

ID_PREFIX = 'logprobs'
DOCS = """
![screenshot of logprobs module in action](./boost-logprobs.png)

Visualizes token confidence during LLM generation using logprobs.

Each token is displayed with background coloring based on model confidence:
- Transparent: high confidence (model is sure)
- Red tint: low confidence (model is uncertain)

Hover over tokens to see alternative tokens the model considered.

Before generation, a "warmup" request determines the logprob range
for the current model, ensuring accurate visualization.

```bash
# Enable the module
harbor boost modules add logprobs
```
"""

logger = log.setup_logger(ID_PREFIX)
current_dir = os.path.dirname(os.path.abspath(__file__))
artifact_path = os.path.join(
  current_dir,
  '..',
  'custom_modules',
  'artifacts',
  'logprobs_mini.html',
)

PROBE_PROMPT = "What is the answer to life, the universe and everything? Only give me the number."


async def probe_logprob_range(llm: 'llm_module.LLM'):
  """
  Run a warmup request to determine logprob range for this model.
  The "42" response should have logprob ≈ 0 (most confident).
  Other alternatives show the uncertain end of the range.
  """
  probe_chat = ch.Chat.from_conversation([
    {"role": "user", "content": PROBE_PROMPT}
  ])

  response = await llm.chat_completion(
    chat=probe_chat,
    params={
      "max_tokens": 10,
      "logprobs": True,
      "top_logprobs": 5,
    },
    resolve=False,  # Get raw response with logprobs
  )

  # Extract logprob range from response
  min_logprob = 0
  max_logprob = 0

  try:
    choices = response.get("choices", [])
    if choices:
      logprobs_data = choices[0].get("logprobs", {})
      content = logprobs_data.get("content", [])

      for token_data in content:
        logprob = token_data.get("logprob", 0)
        max_logprob = max(max_logprob, logprob)

        top_logprobs = token_data.get("top_logprobs", [])
        for alt in top_logprobs:
          alt_logprob = alt.get("logprob", 0)
          min_logprob = min(min_logprob, alt_logprob)

  except Exception as e:
    logger.warning(f"Failed to parse probe response: {e}")
    min_logprob = -10
    max_logprob = 0

  # Ensure we have a reasonable range
  if min_logprob >= max_logprob:
    min_logprob = -10
    max_logprob = 0

  logger.info(f"Logprob range: [{min_logprob}, {max_logprob}]")
  return min_logprob, max_logprob


async def apply(chat: 'ch.Chat', llm: 'llm_module.LLM'):
  with open(artifact_path, 'r') as f:
    artifact = f.read()

  min_logprob, max_logprob = await probe_logprob_range(llm)

  artifact = artifact.replace('<<min_logprob>>', str(min_logprob))
  artifact = artifact.replace('<<max_logprob>>', str(max_logprob))
  await llm.emit_artifact(artifact)

  llm.params["logprobs"] = True
  llm.params["top_logprobs"] = 5

  await llm.stream_final_completion()
