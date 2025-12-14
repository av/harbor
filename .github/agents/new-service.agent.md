---
description: 'This agent can drive implementation of a new service in Harbor.'
tools: ['vscode', 'execute', 'read', 'edit', 'search', 'web', 'chromedevtools/chrome-devtools-mcp/*', 'context7/*', 'deepwiki-mcp/*', 'agent', 'todo']
---
Agent carefully reads and follows the instructions in the file [.github/copilot-new-service.md] to create a new service in Harbor.

### Agent Workflow
- Read the instructions in [.github/copilot-new-service.md] thoroughly.
- Research information about the new service that was provided by the user.
- Use Plan agent to plan the implementation
- Orchestrate the implementation of the new service by breaking down the tasks into manageable steps.
- Delegate writing a documentation to a dedicated sub-agent thread, ensure to refer it to the [./.github/copilot-new-service.md] guide. Ensure that the agent will follow example from 2.3.52 in terms of format and structure.
- Test the implementation based on the service type: CLI - via terminal, Web - via Chrome Automation.

