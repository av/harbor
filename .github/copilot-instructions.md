You will not confuse this project with the Harbor container registry. This is a different project with the same name.
Harbor is a containerized LLM toolkit that allows you to run LLMs and additional services. It consists of a CLI and a companion App that allows you to manage and run AI services with ease.
Harbor is in essence a very large Docker Compose project with extra conventions and tools for managing it.
You can't read `harbor.sh` at once, it's too large for you
Important locations:
- '.' - root, also referred to as `$(harbor home)`
- `harbor.sh` - the main CLI script, it is very large and complex, but it contains the main entry point for the CLI
- `/app` - the Tauri app that provides a GUI for managing services
- `/docs` - documentation for the project and services
- `/routines` - part of the CLI that was rewritten in Deno
- `/.scripts` - scripts for development tasks, written in Deno and Bash
