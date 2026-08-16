# Release 0.5.5 Pending-Changes Integration Tests

Covers the v0.5.4..HEAD range: host-user ownership sweep (ownership/ownership2/ownership3 fact tags),
per-service repair fixes, and lint/compose hygiene.

## Prerequisites
- Docker daemon running; run everything from `/home/everlier/code/harbor` via the `harbor` CLI.
- Do NOT run `harbor logs` (it tails and hangs) — use `docker logs <container>`.
- Never edit `.env` directly; use `harbor config get/set`.
- After each service test, `harbor down` to free resources.

## Test 1: Source lint passes
**Steps:** Run `harbor dev lint --json`.
**Expectations:** Exit code 0; JSON output reports zero errors (warnings acceptable — report them).

## Test 2: Command-facts for the release sweep pass
**Steps:** Run `facts check --tags "ownership or ownership2 or ownership3 or pull-ownership" --has-command`,
then `facts check --tags "sweep9 or notable-sweep or sweep" --has-command`.
**Expectations:** All checked facts report pass; report each failing fact id verbatim.

## Test 3–8: Live ownership boot tests (one test per service)
Services: `karakeep`, `chatui`, `cognee`, `presenton`, `pipelines`, `opencode`.
**Steps (per service):**
1. `harbor up <service>` and wait for containers to be running/healthy (`harbor ps`, `docker ps`).
2. Give the service up to ~2 minutes to write initial state, then inspect the service's bind-mounted
   data dirs under `services/<service>/` on the host.
3. `harbor down`.
**Expectations:**
1. All containers for the service reach running (not restarting/crash-looping; check `docker ps` + `docker logs`).
2. Every file created under the service's workspace/data bind mounts is owned by the host user
   (uid `$(id -u)`), verified with `find services/<service> -newer <marker> ! -uid $(id -u)` returning nothing
   root-owned that the service just wrote.

## Test 9: Manual facts spot-verification for ownership3
**Steps:** For each `?` (manual) fact tagged `ownership3`/`ownership2`, read the referenced compose/entrypoint
files and confirm the claim matches the code.
**Expectations:** PASS/FAIL with a one-line reason per fact.
