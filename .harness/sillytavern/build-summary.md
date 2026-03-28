# Build Summary: SillyTavern Service Fixes

## Changes Made

### 1. Fixed init script seed path (services/sillytavern/harbor-init.sh)
- Removed the `SEED_FILE` variable and the dead write to the non-existent path `/home/node/app/default/content/settings.json`
- For first-time users (no settings.json exists): the script now creates the directory with `mkdir -p` and writes settings.json directly to `/home/node/app/data/default-user/settings.json` with the backend pre-configured
- For returning users (settings.json already exists): patches the file in place, updating only backend type and server URLs while preserving other user settings
- Added `const path = require('node:path')` for `path.dirname()` usage
- Log message updated from "will be seeded from defaults" to "Created settings.json" for the first-time path

### 2. Fixed harbor env CLI regression (harbor.sh)
- In `run_harbor_env`, changed the `*)` default case from `mgr_cmd="unset"` to `mgr_cmd="get"` so that `harbor env <service> <key>` reads and prints the value instead of deleting it
- Fixed the explicit keyword case (`get|set|unset|...`) to use `shift 2` instead of `shift` so that `env_val` correctly captures only the value portion, not the key repeated
- Kept the new `unset`/`rm`/`remove` subcommand in `env_manager` -- it requires explicit keyword usage
- Updated help text to show `env <service> <key>` as "Get" (not "Remove")

### 3. Updated CLI reference docs (docs/3.-Harbor-CLI-Reference.md)
- Changed the `harbor env` documentation to show the short form `harbor env <service> <key>` as "Get a specific env var"
- Added the explicit `harbor env <service> get <key>` as an alternative
- Changed "Remove" to only show `harbor env <service> unset <key>` (explicit keyword required)

### 4. Fixed llamacpp healthcheck (services/compose.llamacpp.yml)
- Replaced `curl -fsS` with a bash `/dev/tcp` approach since the llamacpp server image does not include curl
- Uses the `/health` endpoint which returns "ok" when the server is ready
- Format: `bash -c '{ printf "GET /health HTTP/1.0\r\n\r\n" >&3; cat <&3; } 3<>/dev/tcp/127.0.0.1/8080 | grep -q ok || exit 1'`
- Added `start_period: 30s` to give llamacpp time to load the model before healthcheck failures count

### 5. Fixed Ollama healthcheck (services/compose.ollama.yml)
- The original healthcheck used incorrect CMD-SHELL array syntax with separate elements for `bash`, `-c`, and the command string
- Fixed to use a single string argument to CMD-SHELL: `bash -c '...'`
- Uses the same `/dev/tcp` approach to check the Ollama HTTP endpoint
- Increased `interval` from 1s to 2s, `retries` from 3 to 5, and added `start_period: 10s`
- The previous settings (interval 1s, retries 3, no start_period) gave Ollama only ~3 seconds before being declared unhealthy, causing dependent services to fail immediately

### 6. Cleaned up .gitignore (services/sillytavern/.gitignore)
- Removed duplicate `extensions/` entry
- Verified coverage: `data/`, `config/`, `plugins/`, `extensions/`, `cache/`, `logs/` are all gitignored

### Files not changed (verified correct as-is)
- `services/compose.sillytavern.yml` -- already on harbor-network, port mapping correct
- `services/compose.x.sillytavern.ollama.yml` -- correct depends_on with service_healthy, correct env var
- `services/compose.x.sillytavern.llamacpp.yml` -- correct depends_on with service_healthy, correct env var
- `docs/2.1.15-Frontend-SillyTavern.md` -- already accurate with the fixed behavior (uses `harbor env sillytavern <KEY>` as get)
