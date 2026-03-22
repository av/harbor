---
name: new-boost-module
description: >
  Create new Harbor Boost modules — the Python plugins that run inside Harbor's LLM proxy.
  Use this skill whenever the user wants to build a Boost module, write a custom module for
  Harbor Boost, add a new feature to the Boost proxy pipeline, or create any kind of middleware
  that transforms, augments, or intercepts LLM chat completions in Harbor. Also triggers when
  the user mentions "boost module", "boost plugin", "custom module for boost", or wants to
  add prompt engineering, reasoning chains, or output transforms to Harbor's proxy layer.
---

# Creating Harbor Boost Modules

Harbor Boost is an optimizing LLM proxy with an OpenAI-compatible API. Modules are Python
files that hook into the completion pipeline — they can rewrite prompts, inject system messages,
chain multiple LLM calls, stream artifacts, or replace the completion entirely.

A module is activated by prefixing a model name with the module's `ID_PREFIX`. For example,
a module with `ID_PREFIX = "mymod"` is invoked via model `mymod-llama3.1`.

## Before You Write Code

1. Read the Custom Modules guide: `docs/5.2.1.-Harbor-Boost-Custom-Modules.md`
2. Scan existing modules in `services/boost/src/modules/` to find similar functionality
   you can reuse or learn from. There are 17+ built-in modules covering reasoning chains,
   prompt rewriting, structured output, artifacts, and more.
3. Read the Built-in Modules reference: `docs/5.2.3-Harbor-Boost-Modules.md`

Understanding the available primitives (`chat`, `llm`, `config`, `selection`, `log`) saves
you from reinventing patterns that already exist.

## Module Structure

Every module is a single `.py` file with two required exports:

```python
ID_PREFIX = 'my_module'

async def apply(chat: 'Chat', llm: 'LLM'):
    # Module logic here
    pass
```

### Required Exports

| Export | Type | Purpose |
|--------|------|---------|
| `ID_PREFIX` | `str` | Unique identifier. Becomes the model prefix (e.g., `mymod-llama3.1`). Use lowercase, short, memorable names. |
| `apply` | `async def(chat, llm)` | Entry point called for every matching completion request. |

### Recommended Exports

| Export | Type | Purpose |
|--------|------|---------|
| `DOCS` | `str` | Markdown documentation shown in the Boost modules reference. Include a description, parameters, and usage examples. |
| `logger` | Logger | Created via `log.setup_logger(ID_PREFIX)` for consistent, filterable logging. |

## Core Primitives

### `chat` — The Conversation

`Chat` is a linked list of `ChatNode` objects. The `tail` is the most recent message.

```python
chat.tail.content      # last message text
chat.text()            # full conversation as plain text
chat.history()         # list of dicts from tail upward
chat.user("...")       # append a user message
chat.assistant("...")  # append an assistant message

# Insert a system message before the first message
chat.tail.ancestor().add_parent(
    ch.ChatNode(role="system", content="You are helpful.")
)

# Create a fresh chat for a side-conversation
side = ch.Chat.from_conversation([
    {"role": "user", "content": "Summarize this."}
])
```

### `llm` — The Downstream Model

`llm` talks to the actual LLM backend configured in Boost.

**Output to the client (streamed in real time):**
```python
await llm.emit_message("text")           # raw text chunk
await llm.emit_status("Working...")       # status indicator
await llm.emit_artifact("<html>...</html>")  # Open WebUI artifact
```

**Internal completions (not streamed, returned to you):**
```python
result = await llm.chat_completion(prompt="...", resolve=True)
result = await llm.chat_completion(messages=[...], resolve=True)
result = await llm.chat_completion(chat=some_chat, resolve=True)
# With structured output
result = await llm.chat_completion(prompt="...", schema=MyModel, resolve=True)
```

**Streamed completions (sent to client AND returned):**
```python
text = await llm.stream_chat_completion(prompt="...")
text = await llm.stream_chat_completion(messages=[...])
```

**Final completion (always reaches the client, even with intermediate output disabled):**
```python
await llm.stream_final_completion()                    # from current chat
await llm.stream_final_completion(prompt="Custom prompt")
```

**Boost parameters** — clients can pass `@boost_*` params in the request body:
```python
llm.boost_params  # dict of params without the @boost_ prefix
```

### `config` — Service Configuration

For configurable modules, define config entries in `services/boost/src/config.py` using
the same pattern as existing modules. Config keys follow the `HARBOR_BOOST_<MODULE>_<PARAM>`
convention and are exposed via `harbor boost <module> <param>` CLI.

### `selection` — Message Selection

For modules that operate on specific messages rather than the whole chat, use the selection
module. It provides strategy-based filtering (`all`, `first`, `last`, `match`, etc.) — see
`klmbr`, `eli5`, or `rcn` modules for usage patterns.

## Writing Good DOCS

The `DOCS` string is the user-facing documentation. It should include:

1. A brief description of what the module does and why it's useful
2. Parameter descriptions if the module is configurable
3. Usage examples showing `harbor boost` CLI commands and/or standalone Docker usage

Format example:
```python
DOCS = """
Explains complex questions simply before answering them, improving accuracy
on nuanced prompts.

**Parameters**

- `strat` - message selection strategy. Default: `match`
- `strat_params` - selection filter. Default: matches last user message

```bash
harbor boost modules add eli5
harbor boost eli5 strat match
harbor boost eli5 strat_params role=user,index=-1
```

**Standalone**

```bash
docker run \\
  -e "HARBOR_BOOST_MODULES=eli5" \\
  -e "HARBOR_BOOST_OPENAI_URLS=http://172.17.0.1:11434/v1" \\
  -p 34131:8000 \\
  ghcr.io/av/harbor-boost:latest
```
"""
```

## Common Patterns

**Prompt injection** — add context before the final completion:
```python
async def apply(chat, llm):
    chat.tail.add_parent(ch.ChatNode(role="system", content="Extra context"))
    await llm.stream_final_completion()
```

**Multi-step reasoning** — chain internal completions, then produce a final answer:
```python
async def apply(chat, llm):
    await llm.emit_status("Analyzing...")
    analysis = await llm.chat_completion(prompt="Analyze: {q}", q=chat.tail.content, resolve=True)
    await llm.stream_final_completion(prompt="Given analysis:\n{analysis}\n\nAnswer: {q}",
                                       analysis=analysis, q=chat.tail.content)
```

**Pass-through with side effects** — do something extra while preserving normal behavior:
```python
async def apply(chat, llm):
    logger.info(f"Processing: {chat.tail.content[:50]}")
    await llm.stream_final_completion()
```

## Checklist

Before considering the module done:

- [ ] `ID_PREFIX` is unique, lowercase, and concise
- [ ] `DOCS` export explains functionality, parameters, and includes usage examples
- [ ] `logger = log.setup_logger(ID_PREFIX)` is defined
- [ ] `async def apply(chat, llm)` is the entry point
- [ ] Module file is placed in `services/boost/src/modules/` (built-in) or `boost/src/custom_modules/` (custom)
- [ ] If configurable, config entries added to `services/boost/src/config.py`
- [ ] Documentation in `docs/5.2.3-Harbor-Boost-Modules.md` is updated
