"""Terse output compression for Harbor Boost (JuliusBrussee/caveman-style)."""

from typing import TYPE_CHECKING

import config as boost_config
import log
from modules import style as style_mod
import research.workflow as workflow_mod

if TYPE_CHECKING:
  import chat as ch
  import llm

ID_PREFIX = "caveman"

DOCS = """
`caveman` compresses assistant prose while keeping technical accuracy intact.
It injects terse-communication rules (lite, full, ultra, or wenyan variants) into
the chat before the downstream completion — the well-known "why use many token when
few do trick" workflow adapted for OpenAI-compatible chat completions.

Inspired by [JuliusBrussee/caveman](https://github.com/JuliusBrussee/caveman).

**Parameters**

- `level` — `lite`, `full` (default), `ultra`, `wenyan-lite`, `wenyan-full`,
  `wenyan-ultra`, or `off`

```bash
harbor boost modules add caveman
harbor config set HARBOR_BOOST_CAVEMAN_LEVEL full
```

Users can switch per request with `/caveman lite` or disable with `stop caveman`
/ `normal mode` in the latest user message.

Pair with `ponytail` for minimal code: caveman governs how the model talks,
ponytail governs what it builds.
"""

CAVEMAN_PROMPT = """
Respond in terse caveman style. Keep technical substance; drop fluff.

Rules:
- Drop articles (a/an/the), filler words, and pleasantries.
- Use short sentences and fragments.
- Prefer short synonyms (big not extensive, fix not "implement a solution for").
- Keep technical terms, code, API names, and error strings exact.
- No decorative tables, emojis, or long raw logs.
- Never explain that you are using caveman style.

Examples:
User: What's the best way to learn a new language?
Assistant: Use daily. Speak > read > grammar. Immersion best. Apps help, not enough alone.

User: Why is my Docker container running out of memory?
Assistant: `docker stats` — check limits. Likely none set. Add `--memory=512m`. Still leaks? Profile heap.

User: How does Wi-Fi work?
Assistant: Radio waves. Router ↔ device, 2.4/5 GHz bands. Data in wave modulation. Walls weaken. Closer = faster.
""".strip()

logger = log.setup_logger(ID_PREFIX)


async def apply(chat: "ch.Chat", llm: "llm.LLM", config: dict | None = None):
  cfg = config or {}
  level = style_mod.resolve_style_level(
    chat,
    default=boost_config.CAVEMAN_LEVEL.value,
    config_level=cfg.get("level"),
    module=ID_PREFIX,
  )
  logger.debug(f"{ID_PREFIX}: level={level}")

  return await style_mod.apply_style_and_continue(
    chat,
    llm,
    config,
    module_id=ID_PREFIX,
    prompt=CAVEMAN_PROMPT,
    level=level,
  )
