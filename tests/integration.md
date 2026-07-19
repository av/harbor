# v0.5.3 Release Integration Tests

Verifies the user-facing surface shipped in the v0.5.3 release against a live checkout.

## Prerequisites
- Working directory: repo root (`/home/everlier/code/harbor`); use `./harbor.sh` as the CLI entrypoint.
- Docker daemon running (`docker info` succeeds).
- Host Deno installed (`command -v deno`) — required for Tests 1 and 8.
- For Group B (Tests 5–7): a llamacpp-compatible GGUF model available in the HF cache (the router auto-discovers it); no `HARBOR_LLAMACPP_MODEL` must be set. Start services with `./harbor.sh up llamacpp boost searxng` and wait for health (`./harbor.sh ps`); ALWAYS `./harbor.sh down` when the group finishes. Use `docker logs harbor.boost` — never `harbor logs` (it tails and hangs).

## Group A — CLI behavior (no service state changes)

### Test 1: Host Deno runs show no update-check nag
**Steps:**
1. Run `./harbor.sh ps 2>&1 | cat`.

**Expectations:**
1. Exit code 0.
2. Output contains no "A new release of Deno is available" / upgrade-prompt text (case-insensitive grep for "new release" and "deno upgrade" both empty).

### Test 2: `hf cachedir` rename
**Steps:**
1. Run `./harbor.sh hf cachedir`.
2. Run `./harbor.sh hf --help 2>&1 | cat` (or the hf help path).

**Expectations:**
1. Step 1 exits 0 and prints an existing directory path (test with `[ -d "$path" ]` or at minimum a non-empty absolute path).
2. Help output mentions `cachedir`; the standalone subcommand `cache` is no longer documented as the cache-path printer.

### Test 3: `harbor pull` flag routing
**Steps:**
1. Run `./harbor.sh pull --no-defaults searxng 2>&1 | tee /tmp/pull-test.log`.

**Expectations:**
1. Exit code 0.
2. The log shows an image pull for searxng (docker compose pull output) and contains NO ollama/model-pull invocation and NO occurrence of `--no-defaults` being treated as a model (grep for "pulling model" / ollama output must be empty).

### Test 4: Compose resolver failure fails cleanly
**Steps:**
1. Run `./harbor.sh pull definitely-not-a-real-service-xyz 2>&1; echo "EXIT=$?"`.

**Expectations:**
1. Non-zero exit code reported.
2. Output contains a clear error (not `pull: command not found`); grep for "command not found" must be empty.

## Group B — Boost live modules (starts/stops services; run serially, one agent)

### Test 5: caveman and ponytail are style modules with scoped commands
**Steps:**
1. With services up, `curl -s http://localhost:34131/v1/models` (boost default port; confirm via `./harbor.sh url boost`).
2. Send a chat completion to the boost model with `caveman` applied (per docs/5.2.3): prompt "Explain gravity in a couple sentences."

**Expectations:**
1. `/v1/models` lists caveman/ponytail/quickhop/deephop-prefixed variants of the llamacpp model.
2. The caveman completion returns HTTP 200 with non-empty content and `docker logs harbor.boost` shows no traceback.

### Test 6: quickhop research flow
**Steps:**
1. Send a chat completion through the quickhop model variant with a question that needs current info (e.g. "What is the latest stable Deno version?").

**Expectations:**
1. HTTP 200, non-empty final content.
2. `docker logs harbor.boost` shows the quickhop flow (planning/search/read markers) and no traceback. If SearXNG upstream engines are captcha-blocked, the graceful-degradation path (research-unavailable notice, still-answered response) also counts as PASS — record which path occurred.

### Test 7: token counting survives pathological input
**Steps:**
1. Send a chat completion to any boost model variant whose user message is a single 2,000,000-character string of "a" (generate with python/printf). Set a short `max_tokens` (e.g. 8).

**Expectations:**
1. The request completes (any well-formed HTTP response, including a 4xx rejection) within 120 seconds — no hang, no boost container OOM/restart (`docker ps` shows harbor.boost still up, `docker logs` no traceback).

## Group C — Dev tooling and release artifacts

### Test 8: Strict lint gate is clean
**Steps:**
1. Run `./harbor.sh dev lint --strict; echo "EXIT=$?"`.

**Expectations:**
1. EXIT=0 and output reports no findings.

### Test 9: Test runner auto-prepends install suite
**Steps:**
1. Run `./harbor.sh dev test --suite cli --distros ubuntu-2404 --install-source local --json 2>&1 | tee /tmp/autoinstall-test.log` (long: poll to completion).

**Expectations:**
1. Log contains the auto-prepend notice for the install suite.
2. Both install and cli suites PASS; overall exit 0.

### Test 10: Release artifacts consistent
**Steps:**
1. `gh release view v0.5.3 --json isDraft,tagName -q '"\(.isDraft) \(.tagName)"'`.
2. Compare versions: `./harbor.sh version`, `grep '"version"' app/package.json`, boost `services/boost/pyproject.toml`.

**Expectations:**
1. Release exists, `isDraft=false`, tag `v0.5.3`.
2. All version strings equal `0.5.3`.
