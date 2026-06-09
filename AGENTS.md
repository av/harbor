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
- `tests/` — container-based test runner (suites, rows, orchestrator); see `tests/README.md`
- `.scripts/lint/` — bash-compat lint rules (`HARBORxxx`), fixtures, and 3-pass orchestrator
- `profiles/default.env` — default config distributed to users
- `skills/harbor/SKILL.md` — agent-facing CLI skill (shipped via npm for Claude Code discovery)

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
harbor dev test [--suite ...] [--distros ...] [--json]    # container test matrix
harbor dev lint [--shellcheck|--rules|--compose] [--json] # 3-pass source lint
harbor dev lint-self-test               # validate lint rules against fixtures
```

Dev scripts live in `.scripts/` and must be run via `harbor dev`, not `deno run` directly.

```bash
harbor routine <name>            # run internal Deno routines (routines/)
```

```bash
harbor skills                    # list available agent skills
harbor skills get <name>         # show a skill's content
harbor skills get <name> --full  # show skill + references and templates
harbor skills path [name]        # print skill directory path
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

### Building the App

```bash
# RPM (Fedora — ayatana env vars required)
TAURI_LINUX_AYATANA_APPINDICATOR=1 PKG_CONFIG_PATH="$HOME/.local/lib/pkgconfig" npx tauri build --bundles rpm
```

Fedora ships `libayatana-appindicator-gtk3` instead of `libappindicator-gtk3`. A local `.pc` file at `~/.local/lib/pkgconfig/ayatana-appindicator3-0.1.pc` provides the missing pkg-config entry. Without these env vars the bundler panics.

### Release Notes

When updating the `## News` / changelog section in the `README.md`, always use a bulleted list format: `- **vx.x.x** - one sentence`. Do not use a table.

Release notes are user-facing changelog, not commit messages. Match the style of prior releases (fetch with `gh release view vX.Y.Z --json body`).

- One sentence per bullet about user-observable change. No `—` cause clauses, no implementation rationale.
- Skip changes with no user-visible effect (internal refactors, lint fixes, polish on features introduced in the same release).
- Lead with the symptom or capability, not the mechanism. "Workspace bind mounts now stay owned by your host user" not "`workspace-init` sidecar pattern rolled out."
- Don't enumerate full lists of affected services in-bullet. Say "rolled out to 17 services."

### llamacpp

Never set `llamacpp.model` (`HARBOR_LLAMACPP_MODEL`) config. The router discovers models from the HF cache automatically. Setting it overrides that behavior.

<!-- facts:start -->
## Fact-driven development

This project uses [facts](https://github.com/av/facts) for specification and documentation. All work flows through the fact sheet — it is the source of truth.

**Every change starts with a fact.** Facts are the spec — they define what "done" means. Code that isn't described by a fact is unverifiable and will be treated as incorrect. The skill `facts skills show facts` has the full format spec and command reference.

1. `facts list` — read the current spec to orient. Fact sheets can be large — use filters to focus: `--section "cli/init"`, `--tags "draft"`, `--file api.facts`, `--manual`. Read only the section relevant to your task, not the entire sheet.
2. `facts add` — write facts describing what should be true when done. Each fact is a testable claim. You are not ready to write code until this step is complete.
3. Implement the code to make those facts true
4. `facts check --tags "<tag>"` or `facts get <id>` — verify your changes. Never run bare `facts check` unless asked.
5. `facts edit <id> --add-tag implemented` — mark verified facts done

Step 4 only works if step 2 happened. If you skipped step 2, go back now — you cannot verify work that has no fact.

**Manual facts (`?` in check output):** these have no command, so you verify them by reading the relevant code. For each `?` fact: read what it claims, check the code, report PASS or FAIL with a one-line reason. Reporting "N manual" without verifying each one is not acceptable.

**Lifecycle:** `@draft` → `@spec` → `@implemented`

**Domain:** the `## domain` section in `.facts` defines the project's entities and relations — read it first to learn the vocabulary.

**Skills** (invoke via `facts skills show <name>`):
- `facts-refine` — sharpen `@draft` facts into `@spec` with the user
- `facts-discover` — scan the codebase and sync facts to reality (only when explicitly asked)
- `facts-implement` — implement `@spec` facts in code, verify, tag `@implemented`
<!-- facts:end -->
