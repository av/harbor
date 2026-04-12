## Harbor Project

Harbor is a containerized LLM toolkit — a large Docker Compose project with a CLI and a Tauri app for managing AI services. Not to be confused with Harbor container registry which is a completely different unrelated project. This repository, Harbor, is the LLM toolkit.

### Key Locations

- `harbor.sh` — main CLI (too large to read in full; search for specific functions)
- `services/` — all service directories and compose files (e.g., `services/ollama/`, `services/compose.ollama.yml`)
- `compose.yml` — base compose file, always included
- `app/` — Tauri GUI app
- `docs/` — service and user documentation
- `routines/` — CLI internals rewritten in Deno
- `.scripts/` — dev scripts in Deno/Bash, run via `harbor dev <script>`
- `profiles/default.env` — default config distributed to users

### CLI Reference

```bash
harbor ps                        # list running containers
harbor ls                        # list all available services
harbor up <service>              # start service(s)
harbor down                      # stop and remove containers
harbor logs <service>            # ⚠️ TAILS BY DEFAULT (HANGS AGENT). Use docker logs <container> instead
harbor build <service>
harbor shell <service>           # interactive shell in container
harbor exec <service> <cmd>
harbor eject                     # output standalone Compose config for current selection
$(harbor cmd <service>)          # raw docker compose command for a service
```

```bash
harbor config get <KEY>
harbor config set <KEY> <VALUE>
harbor config update             # propagate profiles/default.env → .env
harbor config search <query>     # search config keys and values
```

**Never edit `.env` directly** — always use `harbor config get/set`.

```bash
harbor env <service>                    # list override vars for a service
harbor env <service> <key>              # get a specific var
harbor env <service> <key> <value>      # set a specific var
```

```bash
harbor dev scaffold <service_name>      # scaffold a new service
harbor dev docs                         # regenerate docs
harbor dev seed                         # seed test data
harbor dev add-logos [--dry-run]        # resolve and write service logos
```

Dev scripts live in `.scripts/` and must be run via `harbor dev`, not `deno run` directly.

```bash
harbor routine <name>            # run internal Deno routines (routines/)
```

### Adding a New Service

Use the `new-service` skill: `.agents/skills/new-service/SKILL.md`.

### Config & Profiles

After editing `profiles/default.env`, run `harbor config update` to apply changes to the current `.env`. The two files are not automatically synced.

### Cross-file Patterns (Service Integration)

`services/compose.x.<service>.<integration>.yml` files are applied when multiple services run together. When a satellite service can use a backend (e.g., Ollama):

1. Add `depends_on` for the backend
2. Mount config templates needed for the integration
3. Set environment variables
4. Override entrypoint if config rendering is needed at startup

Example: `services/compose.x.photoprism.ollama.yml`

### Configurable Models and Backends

- Default model: `HARBOR_<SERVICE>_MODEL` in `profiles/default.env`
- Config templates use `${HARBOR_*}` vars rendered at container startup
- Run `harbor config update` after changing `profiles/default.env`

### Documentation

After any change to service shape (volumes, config, integrations), update the corresponding doc in `docs/` immediately. Cover all new env vars, startup behaviors, and integration steps.

### Service Logos

Logos are static URL strings in [app/src/serviceMetadata.ts](./app/src/serviceMetadata.ts), resolved once via:

```bash
harbor dev add-logos             # resolve and write
harbor dev add-logos --dry-run   # preview only
```

Resolution order: GitHub homepage favicon → dashboardicons.com → GitHub owner avatar.

### Code Quality

- Comments only for non-obvious logic — never restate what the code does
- No emojis in UI or copy — use Lucide icons instead

### Release Notes

When updating the `## News` / changelog section in the `README.md`, always use a bulleted list format: `- **vx.x.x** - one sentence`. Do not use a table.
