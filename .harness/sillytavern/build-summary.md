# Build Summary: SillyTavern Service Fixes

## Changes Made

### 1. Fixed init script seed path (services/sillytavern/harbor-init.sh) -- Round 2

The previous init script created a minimal 2-key `settings.json` from scratch for first-time users. This prevented SillyTavern from seeding its full ~600-line default settings (themes, UI layout, sampler presets, etc.), leaving the UI with broken/missing defaults.

The fix uses a two-pronged approach:

- **Always patch the seed file** at `/home/node/app/default/content/settings.json` (the comprehensive defaults file inside the Docker image). On first startup, SillyTavern copies this seed to the user data directory. By patching it before SillyTavern starts, first-time users get all defaults plus the correct backend configuration.
- **If the live settings file exists (returning user), patch it too** at `/home/node/app/data/default-user/settings.json`. Same logic: update `main_api`, `textgenerationwebui_settings.type`, and `textgenerationwebui_settings.server_urls`.
- **Removed the `else` branch** that created a minimal settings.json from scratch. First-time user seeding is now handled entirely by SillyTavern's own mechanism, with Harbor only pre-patching the seed file.
- Extracted a `patchSettings(filePath)` function to avoid duplicating the patching logic.

### 2. Fixed harbor env CLI regression (harbor.sh) -- Round 1
- In `run_harbor_env`, changed the `*)` default case from `mgr_cmd="unset"` to `mgr_cmd="get"` so that `harbor env <service> <key>` reads and prints the value instead of deleting it
- Fixed the explicit keyword case (`get|set|unset|...`) to use `shift 2` instead of `shift` so that `env_val` correctly captures only the value portion, not the key repeated
- Kept the new `unset`/`rm`/`remove` subcommand in `env_manager` -- it requires explicit keyword usage
- Updated help text to show `env <service> <key>` as "Get" (not "Remove")

### 3. Updated CLI reference docs (docs/3.-Harbor-CLI-Reference.md) -- Round 1
- Changed the `harbor env` documentation to show the short form `harbor env <service> <key>` as "Get a specific env var"
- Added the explicit `harbor env <service> get <key>` as an alternative
- Changed "Remove" to only show `harbor env <service> unset <key>` (explicit keyword required)

### 4. Fixed llamacpp healthcheck (services/compose.llamacpp.yml) -- Round 1
- Replaced `curl -fsS` with a bash `/dev/tcp` approach since the llamacpp server image does not include curl
- Uses the `/health` endpoint which returns "ok" when the server is ready
- Added `start_period: 30s` to give llamacpp time to load the model before healthcheck failures count

### 5. Fixed Ollama healthcheck (services/compose.ollama.yml) -- Round 1
- Fixed incorrect CMD-SHELL array syntax
- Uses the same `/dev/tcp` approach to check the Ollama HTTP endpoint
- Increased `interval` from 1s to 2s, `retries` from 3 to 5, and added `start_period: 10s`

### 6. Cleaned up .gitignore (services/sillytavern/.gitignore) -- Round 1
- Verified coverage: `data/`, `config/`, `plugins/`, `extensions/`, `cache/`, `logs/` are all gitignored

### Files not changed (verified correct as-is)
- `services/compose.sillytavern.yml` -- already on harbor-network, port mapping correct
- `services/compose.x.sillytavern.ollama.yml` -- correct depends_on with service_healthy, correct env var
- `services/compose.x.sillytavern.llamacpp.yml` -- correct depends_on with service_healthy, correct env var
- `docs/2.1.15-Frontend-SillyTavern.md` -- already accurate with the fixed behavior
