# Harbor

Do not confuse this project with the Harbor container registry. This is a different project with the same name.

Harbor is a containerized LLM toolkit that allows you to run LLMs and additional services. It consists of a CLI and a companion App that allows you to manage and run AI services with ease.

# Components

Harbor consists of:
- CLI, primarily written in Bash, see [harbor.sh](../harbor.sh) (VERY large file)
  - CLI is in transition to the TypeScript with Deno, you'll see concept of "routines", this is a preferred way to develop new complex functionality
- Desktop App - written with Tauri, React, DaisyUI, located in the `/app` directory

Harbor is in essence a very large Docker Compose project with extra conventions and tools for managing it.

# Repository structure

- '.' - root, also referred to as `$(harbor home)`
- `/docs` - project and services documentation, note the index system in the file names
- `/app` - Tauri app
- `/http-catalog` - samples of using service APIs
- `/.scripts` - scripts with Deno / Bash for dev-related tasks in the project

# Relevant docs
- [Adding a new service](../docs/7.-Adding-A-New-Service.md)