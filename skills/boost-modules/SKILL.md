```skill
---
name: boost-modules
description: Create custom modules for Harbor Boost, an optimizing LLM proxy. Use when building Python modules that intercept/transform LLM chat completions—reasoning chains, prompt injection, structured outputs, artifacts, or custom workflows. Triggers on requests to create Boost modules, extend LLM behavior via proxy, or implement chat completion middleware.
---

# Harbor Boost Custom Modules

Boost modules are Python files that intercept chat completions and can transform, augment, or replace LLM responses.

## Module Structure

```python
ID_PREFIX = 'mymodule'  # Models prefixed with this trigger the module

async def apply(chat, llm):
    # chat: conversation history (linked list of ChatNodes)
    # llm: interface to downstream LLM and output streaming
    await llm.stream_final_completion()
```

## Quick Reference

### Output Methods

```python
# Stream text to client
await llm.emit_message("Hello")

# Status indicator (formatted per HARBOR_BOOST_STATUS_STYLE)
await llm.emit_status("Processing...")

# Internal completion (not streamed to client)
result = await llm.chat_completion(prompt="Summarize: {text}", text=content, resolve=True)

# Streamed completion (visible to client)
await llm.stream_chat_completion(prompt="Explain {topic}", topic="quantum")

# Final completion (always streamed, even when intermediate output disabled)
await llm.stream_final_completion()
await llm.stream_final_completion(prompt="Reply to: {msg}", msg=chat.tail.content)

# Structured output
from pydantic import BaseModel, Field
class Response(BaseModel):
    answer: str = Field(description="The answer")
result = await llm.chat_completion(prompt="...", schema=Response, resolve=True)

# Artifacts (for clients like Open WebUI)
await llm.emit_artifact("<h1>Interactive content</h1>")
```

### Chat Manipulation

```python
# Read conversation
chat.text()           # Full conversation as string
chat.message          # Last user message content
chat.tail             # Last ChatNode
chat.tail.content     # Content of last message
chat.tail.role        # Role of last message
chat.history()        # List of messages from tail
chat.plain()          # List of ChatNodes from tail

# Add messages
chat.user("New user message")
chat.assistant("New assistant message")
chat.add_message(role="system", content="Custom instruction")

# Navigate/modify tree
chat.tail.parent           # Parent node
chat.tail.parents()        # All ancestors
chat.tail.ancestor()       # Root node
chat.tail.add_child(ChatNode(role="user", content="..."))
chat.tail.add_parent(ChatNode(role="system", content="..."))

# Create new chat
import chat as ch
new_chat = ch.Chat.from_conversation([
    {"role": "user", "content": "Hello"}
])
```

### Request Parameters

Custom params prefixed with `@boost_` in the request body:

```python
# Request: {"model": "mymodule-gpt4", "@boost_mode": "verbose"}
async def apply(chat, llm):
    mode = llm.boost_params.get("mode")  # "verbose"
```

## Standalone Docker Setup

```bash
docker run \
  -e "HARBOR_BOOST_OPENAI_URLS=http://172.17.0.1:11434/v1" \
  -e "HARBOR_BOOST_OPENAI_KEYS=sk-ollama" \
  -e "HARBOR_BOOST_MODULES=mymodule" \
  -e "HARBOR_BOOST_BASE_MODELS=true" \
  -v /path/to/modules:/app/custom_modules \
  -p 8000:8000 \
  ghcr.io/av/harbor-boost:latest
```

Key environment variables:
- `HARBOR_BOOST_OPENAI_URLS` / `HARBOR_BOOST_OPENAI_KEYS`: Semicolon-separated backend URLs and keys (index-matched)
- `HARBOR_BOOST_MODULES`: Semicolon-separated list of enabled modules (or `all`)
- `HARBOR_BOOST_BASE_MODELS`: Set `true` to also serve unmodified models
- `HARBOR_BOOST_API_KEY`: Protect the boost API with a key
- `HARBOR_BOOST_INTERMEDIATE_OUTPUT`: Show reasoning/status (default: true)

## Example Modules

### Echo (Minimal)
```python
ID_PREFIX = 'echo'

async def apply(chat, llm):
    await llm.emit_message(chat.message)
```

### System Prompt Injection
```python
import chat as ch

ID_PREFIX = 'pirate'

async def apply(chat, llm):
    chat.tail.ancestor().add_child(
        ch.ChatNode(role='system', content='Respond as a pirate.')
    )
    await llm.stream_final_completion()
```

### Chain of Thought
```python
ID_PREFIX = 'cot'

async def apply(chat, llm):
    await llm.emit_status("Thinking...")
    reasoning = await llm.chat_completion(
        prompt="Think step by step about: {q}\nProvide reasoning only.",
        q=chat.message,
        resolve=True
    )
    await llm.emit_message(f"**Reasoning:**\n{reasoning}\n\n**Answer:**\n")
    await llm.stream_final_completion(
        prompt="Given this reasoning:\n{reasoning}\n\nProvide a final answer to: {q}",
        reasoning=reasoning,
        q=chat.message
    )
```

### URL Reader
```python
import re
import requests

ID_PREFIX = "readurl"

url_regex = r"https?://[^\s]+"

async def apply(chat, llm):
    urls = re.findall(url_regex, chat.message)
    if not urls:
        return await llm.stream_final_completion()
    
    content = ""
    for url in urls:
        await llm.emit_status(f"Fetching {url}...")
        content += requests.get(url).text[:5000]
    
    await llm.stream_final_completion(
        prompt="<content>\n{content}\n</content>\n\nUser request: {request}",
        content=content,
        request=chat.message
    )
```

## Development Workflow

1. Create module file in mounted `custom_modules/` directory
2. Restart container on first load (hot reload works after)
3. Test via API:
   ```bash
   curl http://localhost:8000/v1/models  # Verify module appears
   curl -X POST http://localhost:8000/v1/chat/completions \
     -H "Content-Type: application/json" \
     -d '{"model":"mymodule-llama3","messages":[{"role":"user","content":"test"}]}'
   ```
4. Check logs for debug output: `docker logs -f <container>`

## Debugging

```python
import log
logger = log.setup_logger('mymodule')

async def apply(chat, llm):
    logger.debug(f"Input: {chat.message}")
    logger.info("Processing started")
```

Logs appear in container stdout. Set `DEBUG` log level for verbose output.
```
