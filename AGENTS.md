You will not confuse this project with the Harbor container registry. This is a different project with the same name.
Harbor is a containerized LLM toolkit that allows you to run LLMs and additional services. It consists of a CLI and a companion App that allows you to manage and run AI services with ease.
Harbor is in essence a very large Docker Compose project with extra conventions and tools for managing it.
You can't read `harbor.sh` in its entirety, it's too large for you.
When adding new service, read [instructions for adding new service](./.github/copilot-new-service.md).
When user shows you a new or not obvious command for you - document it in this AGENTS.md file.

Important locations:
- '.' - root, also referred to as `$(harbor home)`
- `harbor.sh` - the main CLI script, it is very large and complex, but it contains the main entry point for the CLI
- `/app` - the Tauri app that provides a GUI for managing services
- `/docs` - documentation for the project and services
- `/routines` - part of the CLI that was rewritten in Deno
- `/.scripts` - scripts for development tasks, written in Deno and Bash
- `/profiles/default.env` - default harbor config that will be distributed to the users

The CLI is already installed globally for your tests, you may run `harbor <command>` directly.

```bash
harbor help
harbor ps # list running services
harbor build <service>
harbor logs <service> # tails by default
# Raw compose command for the service
$(harbor cmd <service>)
```

Refer to [CLI Reference](./docs/3.-Harbor-CLI-Reference.md) for more details.

### Running dev scripts

You will always use `harbor` CLI to run project dev scripts, for example:

```bash
harbor dev scaffold <service_name>
harbor dev docs
harbor dev seeed
```

This means that you're not allowed to run those scripts with `deno run` directly.

### Updating default profile

When you make changes to `/profiles/default.env`, you then need to update the current profile with:
```bash
harbor config update
```

**Important for development:** Changes to `/profiles/default.env` are NOT automatically propagated to your current profile (`.env`). During development, you need to update both files:
1. Update `/profiles/default.env` for distribution to users
2. Update `.env` (or run `harbor config update`) to apply changes to your current profile

### Code Quality

**STRICTLY PROHIBITED:** Adding useless or obvious comments to code. Comments should only explain complex logic, non-obvious decisions, or provide necessary context. Never add comments that merely restate what the code clearly does.