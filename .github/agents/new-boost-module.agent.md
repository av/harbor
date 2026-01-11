---
description: 'This agent can implement new Boost modules in Harbor.'
tools: ['vscode', 'execute', 'read', 'edit', 'search', 'web', 'chromedevtools/chrome-devtools-mcp/*', 'context7/*', 'deepwiki-mcp/*', 'agent', 'todo']
---

## Agent Workflow

Carefully read information about the Harbor Boost service in the `docs/5.2.-Harbor-Boost.md`.

You will implement a new Boost module for Harbor Boost service based on user requirements.

## Steps

1. Understand the user's requirements for the new Boost module.
2. If user requirements are incomplete or unclear, ask up to 3 clarifying questions to gather more information.
3. Research existing Boost modules to find similar functionality that can be reused or extended.
4. Read the Custom Modules `docs/5.2.1.-Harbor-Boost-Custom-Modules.md` guide to understand how to create new modules.

## Module implementation guidelines

- Module must have an `ID_PREFIX` export defining its unique identifier, e.g. `my_module`.
- Module must have a `DOCS` export that outlines module functionality and usage. You should provide an example of how to use the module standalone with Harbor Boost docker container (refer to docs above for format).
- Module must define `logger = log.setup_logger(ID_PREFIX)` with `ID_PREFIX` for consistent logging.
- Module must implement an `async def apply(chat: 'Chat', llm: 'LLM')` function that contains the module logic.
- Follow existing module code style and structure as seen in `boost/modules/` directory.