import random

import chat as ch
import llm
import log

ID_PREFIX = 'fml'
DOCS = """
`fml` - "Formulaic" (not the other thing)

Rewrites original request in a formulaic logic language (whatever LLM will mean by that),
solves it, and rewrites the solution in natural language.
"""

async def apply(chat: 'ch.Chat', llm: 'llm.LLM'):
  chat.user(
    f"""
Rewrite my request in the formulaic logic language. Do not solve it yet.
    """.strip()
  )
  await chat.emit_status('Formulaic')
  await chat.emit_advance()

  chat.user(
    f"""
Solve my original request in the formulaic logic language.
""".strip()
  )
  await chat.emit_status('Solution')
  await chat.emit_advance()

  chat.user(
    f"""
Rewrite it in the natural language.
""".strip()
  )

  await chat.emit_status('Final')
  await llm.stream_final_completion()
