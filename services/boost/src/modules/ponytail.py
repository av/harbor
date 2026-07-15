"""YAGNI minimal-code reasoning for Harbor Boost (DietrichGebert/ponytail-style)."""

from typing import TYPE_CHECKING

import config as boost_config
import log
from modules import style as style_mod

if TYPE_CHECKING:
  import chat as ch
  import llm

ID_PREFIX = "ponytail"

DOCS = """
`ponytail` channels the lazy-senior-dev ladder: YAGNI, stdlib first, native platform
features before dependencies, one line before fifty. It injects build-discipline rules
before the downstream completion.

Inspired by [DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail).

**Parameters**

- `level` — `lite`, `full` (default), `ultra`, or `off`

```bash
harbor boost modules add ponytail
harbor config set HARBOR_BOOST_PONYTAIL_LEVEL full
```

Users can switch per request with `/ponytail ultra` or disable with `stop ponytail`
/ `normal mode` in the latest user message.

Ponytail governs what you build, not how you talk — pair with `caveman` for terse prose.
"""

PONYTAIL_PROMPT = """
You are a lazy senior developer. Lazy means efficient, not careless.
The best code is the code never written.

ACTIVE EVERY RESPONSE unless level is off.

THE LADDER — stop at the first rung that holds:
1. Does this need to exist at all? (YAGNI)
2. Stdlib does it?
3. Native platform feature covers it?
4. Already-installed dependency solves it?
5. Can it be one line?
6. Only then: the minimum code that works.

No unrequested abstractions. No boilerplate for later. Deletion over addition.
Fewest files. Shortest working diff wins.
Mark deliberate shortcuts with a ponytail: comment naming the upgrade path.

Output: code first, then at most three short lines on what was skipped.
Never simplify away trust-boundary validation, data-loss handling, security, or
accessibility. User insists on the full version → build it without re-arguing.
""".strip()

logger = log.setup_logger(ID_PREFIX)


async def apply(chat: "ch.Chat", llm: "llm.LLM", config: dict | None = None):
  cfg = config or {}
  level = style_mod.resolve_style_level(
    chat,
    default=boost_config.PONYTAIL_LEVEL.value,
    config_level=cfg.get("level"),
  )
  logger.debug(f"{ID_PREFIX}: level={level}")
  return await style_mod.apply_style_and_continue(
    chat,
    llm,
    config,
    module_id=ID_PREFIX,
    prompt=PONYTAIL_PROMPT,
    level=level,
  )