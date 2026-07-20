# Harbor Services Integration Test Specification

Verifies that common Harbor services start correctly and perform one basic
function each. All checks are strictly command-verifiable — every test states
an exact command and an expected, machine-checkable outcome.

Run groups **serially** (services share ports and the GPU). Always run
`./harbor.sh down` at the end of a group, even on failure. Never use
`harbor logs` (it tails and hangs unattended runs) — use
`docker logs harbor.<service>` instead.

## Prerequisites

- Docker with the compose plugin; current user can run `docker`.
- Harbor checkout at repo root; all commands below run from repo root.
- At least one GGUF model in the HF cache (`~/.cache/huggingface/hub`) for
  llamacpp-backed tests. This spec uses `unsloth/Qwen3.5-0.8B-GGUF`
  (CPU-friendly). The llamacpp router discovers cached models automatically —
  do **not** set `llamacpp.model`.
- Boost auth: API key is `sk-boost` (`./harbor.sh config get boost.api_key`).
- Host tools for Group C installed on the host: `hermes`
  (`~/.local/bin/hermes`) and `opencode` (`~/.opencode/bin/opencode`).
- Network access for image pulls and (Group D) the Ollama model pull.
- No prior Harbor stack running: start each group from `./harbor.sh down`.

Conventions:

- `URL=$(./harbor.sh url <svc>)` — resolves host URL of a running service.
- A "200 probe" means: `curl -s -o /dev/null -w '%{http_code}' "$URL<path>"`
  prints `200`.
- Readiness loops: poll the probe every 5 s, up to 120 s (llamacpp: 300 s to
  allow model load; webui/langflow: 300 s for first-boot migrations).
- Record every check as CHECK / COMMAND / EXPECTED / ACTUAL / RESULT.

Model id note: the llamacpp router exposes cached models with ids visible via
`curl -s $(./harbor.sh url llamacpp)/v1/models`. Set
`MODEL=$(curl -s "$(./harbor.sh url llamacpp)/v1/models" | jq -r '.data[].id' | grep -i 'Qwen3.5-0.8B' | head -1)`
and reuse it in all LLM checks below.

## Services covered

| Service  | Kind                  | Group | Needs model/GPU |
|----------|-----------------------|-------|-----------------|
| llamacpp | LLM backend           | A     | GGUF in HF cache (CPU OK) |
| webui    | Web frontend          | A     | via llamacpp |
| boost    | LLM proxy/middleware  | A     | via llamacpp |
| litellm  | LLM gateway           | A     | via llamacpp |
| aichat   | container CLI client  | A     | via llamacpp |
| searxng  | metasearch engine     | B     | none |
| langflow | visual agent builder  | B     | none for startup |
| hermes   | host coding agent     | C     | llamacpp running |
| opencode | host coding agent     | C     | llamacpp running |
| ollama   | LLM backend           | D     | pulls a small model (CPU OK) |
| gptme    | container CLI agent   | D     | via ollama |
| comfyui  | image gen (optional)  | E     | GPU + checkpoint; startup-only check |

## Group A — llamacpp backend + OpenAI-compatible satellites

Start: `./harbor.sh up llamacpp webui boost litellm`

(Do **not** include `aichat` in `up` — it is a run-style CLI container that
exits immediately without a TTY, which makes `harbor up` report a startup
failure. It is exercised via `harbor run` in A5.)

### A1. llamacpp

- Ready: 200 probe on `$(./harbor.sh url llamacpp)/health` (≤300 s).
- Function: chat completion returns non-empty content.
  ```
  curl -s "$(./harbor.sh url llamacpp)/v1/chat/completions" \
    -H 'Content-Type: application/json' \
    -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly: PONG\"}],\"max_tokens\":2000}" \
    | jq -er '.choices[0].message.content | length > 0'
  ```
  Expected: exit 0, prints `true`. (`max_tokens` must be generous: Qwen3.5 is
  a thinking model — a small budget is consumed entirely by
  `reasoning_content`, leaving `content` empty.)

### A2. webui (Open WebUI)

- Ready: container `harbor.webui` reports healthy:
  `docker inspect -f '{{.State.Health.Status}}' harbor.webui` prints `healthy`
  (≤300 s), and 200 probe on `$(./harbor.sh url webui)/health`.
- Function: webui sees llamacpp models through its config API is auth-gated;
  instead verify the app serves its SPA and version endpoint:
  `curl -s "$(./harbor.sh url webui)/api/version" | jq -er '.version'`
  Expected: prints a semver-like string, exit 0.

### A3. boost

- Ready: 200 probe on `$(./harbor.sh url boost)/health` (≤120 s).
- Function: authenticated model list includes at least one boosted model, and
  a plain passthrough completion works:
  ```
  curl -s -H 'Authorization: Bearer sk-boost' "$(./harbor.sh url boost)/v1/models" \
    | jq -er '.data | length > 0'
  BOOSTED=$(curl -s -H 'Authorization: Bearer sk-boost' "$(./harbor.sh url boost)/v1/models" | jq -r '.data[].id' | grep -i "$MODEL" | head -1)
  curl -s "$(./harbor.sh url boost)/v1/chat/completions" \
    -H 'Authorization: Bearer sk-boost' -H 'Content-Type: application/json' \
    -d "{\"model\":\"$BOOSTED\",\"messages\":[{\"role\":\"user\",\"content\":\"Say OK\"}],\"max_tokens\":2000}" \
    | jq -er '.choices[0].message.content | length > 0'
  ```
  Expected: both jq commands exit 0.
- Negative: same completion without the Bearer header returns HTTP 401.

### A4. litellm

- Ready: 200 probe on `$(./harbor.sh url litellm)/health/liveliness` (≤120 s).
- Function: `curl -s -H "Authorization: Bearer sk-litellm" "$(./harbor.sh url litellm)/v1/models" | jq -er '.data'` exits 0
  (key: `./harbor.sh config get litellm.master.key`; use that value if it
  differs from `sk-litellm`). Note: Harbor ships no
  `compose.x.litellm.llamacpp.yml` overlay, so the list is `[]` when only
  llamacpp runs — an empty array is a PASS for this check.

### A5. aichat (container CLI)

- Pre: aichat's model id must match a llamacpp router id — the shipped
  default (`qwen3.5:4b`) is an ollama-style tag that llamacpp rejects with
  "model not found". Save the current value, then
  `./harbor.sh config set aichat.model "$MODEL"`; restore afterwards.
- Function (doubles as readiness):
  `timeout 600 ./harbor.sh run aichat --no-stream 'Reply with exactly: PONG' </dev/null`
  — capture stdout; Expected: exit 0 and non-empty stdout (LLM output; do
  not require exact string match, only `[ -n "$out" ]`).
  Do **not** use `-e` (execute-command mode prompts for confirmation and
  hangs unattended runs); pass `</dev/null` and `--no-stream` so the
  one-shot never blocks on a TTY. If the run times out, remove leftover
  `harbor-aichat-run-*` containers — abandoned runs keep llamacpp slots
  generating and can exhaust the context for later requests.

Teardown: `./harbor.sh down`

## Group B — standalone web services (no LLM)

Start: `./harbor.sh up searxng langflow`

### B1. searxng

- Ready: 200 probe on `$(./harbor.sh url searxng)/` (≤120 s).
- Function: JSON search returns a results array:
  `curl -s "$(./harbor.sh url searxng)/search?q=harbor&format=json" | jq -er '.results | type == "array"'`
  Expected: prints `true`, exit 0. (If format=json is 403, verify instead
  that `curl -s "$URL/search?q=harbor"` returns HTTP 200 with body containing
  `<html` — settings gate the JSON format.)

### B2. langflow

- Ready: 200 probe on `$(./harbor.sh url langflow)/health` (≤300 s; first
  boot runs DB migrations).
- Function: `curl -s "$(./harbor.sh url langflow)/api/v1/version" | jq -er '.version'` exits 0.

Teardown: `./harbor.sh down`

## Group C — host coding tools (hermes, opencode) via `harbor launch`

These are **host** CLIs, not long-running containers. `harbor launch` starts
llamacpp automatically if no backend runs, generates the tool config, and
execs the tool. Run non-interactively with a one-shot prompt.

Pre: `./harbor.sh up llamacpp` and wait for A1 readiness (reuse `$MODEL`).

### C1. hermes

- Command (non-interactive, timeboxed):
  `timeout 300 ./harbor.sh launch --backend llamacpp --model "$MODEL" hermes "Reply with exactly: PONG and nothing else" </dev/null`
  (adjust to hermes' non-interactive flag if it requires one — check
  `hermes --help`; the launch adapter passes args through unchanged).
- Expected: exit 0 and non-empty stdout containing model output. If hermes is
  interactive-only, the fallback check is: the adapter resolves and prints the
  configured env (`OPENAI_BASE_URL` pointing at llamacpp) and the tool starts —
  verified by `timeout 20 ... </dev/null; [ $? -ne 127 ]` plus no
  "connection refused" in output.

### C2. opencode

- Command:
  `timeout 300 ./harbor.sh launch --backend llamacpp --model "$MODEL" opencode run "Reply with exactly: PONG and nothing else"`
- Expected: exit 0, non-empty stdout. `opencode run` is the documented
  non-interactive mode; the launch adapter injects `OPENCODE_CONFIG_CONTENT`
  pointing the `harbor` provider at llamacpp.

Teardown: `./harbor.sh down`

## Group D — ollama backend + gptme

Start: `./harbor.sh up ollama gptme`

### D1. ollama

- Ready: `curl -s "$(./harbor.sh url ollama)/api/version" | jq -er '.version'`
  exits 0 (≤120 s).
- Function: pull a tiny model and generate:
  ```
  ./harbor.sh exec ollama ollama pull qwen3:0.6b
  curl -s "$(./harbor.sh url ollama)/api/generate" \
    -d '{"model":"qwen3:0.6b","prompt":"Reply with exactly: PONG","stream":false}' \
    | jq -er '.response | length > 0'
  ```
  Expected: pull exits 0; jq prints `true`.

### D2. gptme (container CLI, ollama overlay)

- Function: `timeout 300 ./harbor.sh run gptme --non-interactive 'Reply with exactly: PONG'`
  Expected: exit 0, non-empty stdout. (If `--non-interactive` is not a valid
  flag, use `-n` / check `./harbor.sh run gptme --help`; record the working
  invocation in results.)

Teardown: `./harbor.sh down`

## Group E — comfyui (optional; GPU)

Only run on a host with a working GPU runtime. No model checkpoint is
required for the startup check; image generation is out of scope here.

Start: `./harbor.sh up comfyui`

### E1. comfyui

- Ready: 200 probe on `$(./harbor.sh url comfyui)/` (≤300 s; first boot
  downloads assets via comfyui-init).
- Function: `curl -s "$(./harbor.sh url comfyui)/system_stats" | jq -er '.system'` exits 0.

Teardown: `./harbor.sh down`

## Results

Execution results are appended per run as:

```
### Run <date> — Group <X>
CHECK: <id>
COMMAND: <exact command>
EXPECTED: <expected>
ACTUAL: <observed>
RESULT: PASS | FAIL | SKIP (<reason>)
```

Failures are triaged as product defect (fix in repo, fact-driven) vs.
environment issue (document only).

### Run 2026-07-20 — Group A

`MODEL=unsloth/Qwen3.5-0.8B-GGUF:Q4_K_M` (llamacpp router auto-discovered).

CHECK: A1 llamacpp ready
COMMAND: 200 probe on `$(./harbor.sh url llamacpp)/health` (poll 5 s)
EXPECTED: 200 within 300 s
ACTUAL: 200 on first poll
RESULT: PASS

CHECK: A1 llamacpp chat completion
COMMAND: `curl -s $URL/v1/chat/completions -d '{"model":"'$MODEL'","messages":[{"role":"user","content":"Reply with exactly: PONG"}],"max_tokens":2000}' | jq -er '.choices[0].message.content | length > 0'`
EXPECTED: prints `true`, exit 0
ACTUAL: `true` (content `PONG`, finish_reason `stop`, 824 completion tokens incl. reasoning)
RESULT: PASS — after spec fix: original `max_tokens:30` was entirely consumed by `reasoning_content` (thinking model), leaving empty `content`. Bad spec expectation, not a defect; spec updated to 2000.

CHECK: A2 webui ready
COMMAND: `docker inspect -f '{{.State.Health.Status}}' harbor.webui`; 200 probe on `$URL/health`
EXPECTED: `healthy` + 200 within 300 s
ACTUAL: `healthy`, probe 200
RESULT: PASS

CHECK: A2 webui version
COMMAND: `curl -s $URL/api/version | jq -er '.version'`
EXPECTED: semver, exit 0
ACTUAL: `0.9.6`
RESULT: PASS

CHECK: A3 boost ready
COMMAND: 200 probe on `$(./harbor.sh url boost)/health`
EXPECTED: 200 within 120 s
ACTUAL: 200 on first poll
RESULT: PASS

CHECK: A3 boost model list
COMMAND: `curl -s -H 'Authorization: Bearer sk-boost' $URL/v1/models | jq -er '.data | length > 0'`
EXPECTED: `true`, exit 0
ACTUAL: `true` (boosted ids e.g. `autotemp-unsloth/Qwen3.5-0.8B-GGUF:Q4_K_M`)
RESULT: PASS

CHECK: A3 boost completion
COMMAND: completion via `autotemp-unsloth/Qwen3.5-0.8B-GGUF:Q4_K_M`, max_tokens 2000
EXPECTED: non-empty content, exit 0
ACTUAL: `true`
RESULT: PASS

CHECK: A3 boost 401 without auth
COMMAND: same completion without Bearer header, `-w '%{http_code}'`
EXPECTED: 401
ACTUAL: 401
RESULT: PASS

CHECK: A4 litellm ready
COMMAND: 200 probe on `$URL/health/liveliness`
EXPECTED: 200 within 120 s
ACTUAL: 200 on first poll
RESULT: PASS

CHECK: A4 litellm models
COMMAND: `curl -s -H "Authorization: Bearer sk-litellm" $URL/v1/models | jq -er '.data'`
EXPECTED: exit 0
ACTUAL: `[]`, exit 0 — expected: no `compose.x.litellm.llamacpp.yml` overlay exists, so llamacpp adds no litellm models
RESULT: PASS

CHECK: A5 aichat one-shot
COMMAND: `timeout 600 ./harbor.sh run aichat --no-stream 'Reply with exactly: PONG' </dev/null` (after `harbor config set aichat.model "$MODEL"`)
EXPECTED: exit 0, non-empty stdout
ACTUAL: exit 0, model output produced (thinking preamble + answer)
RESULT: PASS — after two spec fixes: (1) `-e` flag hangs (execute-command confirmation prompt) — replaced with plain prompt + `--no-stream` + `</dev/null`; (2) shipped default `aichat.model=qwen3.5:4b` is an ollama-style tag rejected by llamacpp ("model not found") — the check must set aichat.model to a llamacpp router id. Also observed: timed-out `harbor run` containers keep llamacpp generating until context exhaustion; cleanup of `harbor-aichat-run-*` containers required before retry.

Triage summary: no product defects. Two bad spec expectations fixed
(max_tokens too small for thinking models; aichat `-e` interactive hang) and
one environment/config note (aichat default model id vs llamacpp ids;
no litellm-llamacpp overlay by design).

Teardown: `./harbor.sh down` executed; `aichat.model` restored to
`qwen3.5:4b`.
