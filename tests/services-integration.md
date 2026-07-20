# Harbor Services Integration Test Specification

Verifies that common Harbor services start correctly and perform one basic
function each. All checks are strictly command-verifiable — every test states
an exact command and an expected, machine-checkable outcome.

Run groups **serially** (services share ports and the GPU). Always run
`./harbor.sh down` at the end of a group, even on failure. Never use
`harbor logs` (it tails and hangs unattended runs) — use
`docker logs harbor.<service>` instead.

## Prerequisites

> Automated runner: `./tests/services-integration.sh` executes this spec's
> checks group by group (`--list` shows groups, `--groups B,G` selects a
> subset; Group E is opt-in). It encodes the operational notes below —
> serial groups with teardown, token budgets, run-style invocation, stray
> run-container cleanup, config save/restore — and prints PASS/FAIL per
> check with a nonzero exit on any failure.

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
| jupyter  | notebook server       | F     | none (CUDA base image runs on CPU) |
| chatui   | web frontend          | F     | via ollama overlay (startup check) |
| librechat| web frontend (5 ctrs) | F     | none for startup |
| promptfoo| eval web server       | F     | none for startup |
| fabric   | container CLI         | G     | via ollama |
| cmdh     | container CLI         | G     | via ollama |

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
  generating and can exhaust the context for later requests. Removing the
  client container alone does **not** stop the slot — llamacpp keeps
  decoding the orphaned request; `docker restart harbor.llamacpp` before
  retrying, then re-wait for `/health` 200.

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
- Model caveat: opencode sends a system message that is not first in the
  request; models whose chat template raises on that (e.g. Qwen3.5's
  "System message must be at the beginning") make llama.cpp return 400
  during automatic tool-parser generation. Use a template-tolerant model
  (e.g. `LiquidAI/LFM2.5-8B-A1B-GGUF:Q8_0`) for this check. Note:
  `opencode run` exits 0 even on API errors — assert on output content,
  not exit code alone.

Teardown: `./harbor.sh down`

## Group D — ollama backend + gptme

Start: `./harbor.sh up ollama`

(Do **not** include `gptme` in `up` — like aichat it is a run-style CLI
container. It is exercised via the dedicated `harbor gptme` subcommand in D2,
which injects `-m local/$(harbor config get gptme.model)` and runs the
container with the ollama overlay.)

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

- Pre: gptme's model must exist in ollama — save the current value, then
  `./harbor.sh config set gptme.model qwen3:0.6b`; restore afterwards
  (shipped default `qwen3.5:4b` is not pulled by D1).
- Function:
  `timeout 300 ./harbor.sh gptme -n --no-stream 'Reply with exactly: PONG' </dev/null`
  Expected: exit 0, non-empty stdout containing model output. Notes: use the
  `harbor gptme` subcommand, not `harbor run gptme` — only the subcommand
  passes `-m local/<gptme.model>`; gptme's non-interactive flag is
  `-n/--non-interactive` (implies `--no-confirm`). In autonomous mode gptme
  auto-replies twice asking for tool calls, then exits 0 on its own — that is
  normal for a plain-text prompt.

Teardown: `./harbor.sh down`

## Group E — comfyui (optional; GPU)

No model checkpoint is required for the startup check; image generation is
out of scope here. The shipped image is `ghcr.io/ai-dock/comfyui:latest-cuda`;
on a host **without** an NVIDIA driver the ComfyUI process fatals at boot
(`RuntimeError: Found no NVIDIA driver`) while the container itself stays Up
(supervisor keeps running). For a GPU-less startup check, set
`./harbor.sh config set comfyui.args "--cpu"` first and restore it afterwards.

Start: `./harbor.sh up comfyui`

### E1. comfyui

- Ready: 200 probe on `$(./harbor.sh url comfyui)/` (≤300 s; first boot
  downloads assets via comfyui-init).
- Function: `curl -s "$(./harbor.sh url comfyui)/system_stats" | jq -er '.system'` exits 0.

Teardown: `./harbor.sh down`

## Group F — web services batch 2 (jupyter, chatui, librechat, promptfoo)

Start: `./harbor.sh up ollama jupyter chatui librechat promptfoo`

(ollama is included so the chatui/librechat-rag ollama overlays resolve their
backend URL; no model pull is required — Group F checks are startup + HTTP
probes only. jupyter is a local build on a large PyTorch CUDA base image; the
first `up` may spend several minutes pulling/building — it runs fine on CPU.)

### F1. jupyter

- Ready: 200 probe on `$(./harbor.sh url jupyter)/api` (≤600 s; first boot
  pulls/builds the PyTorch base image).
- Function: `curl -s "$(./harbor.sh url jupyter)/api" | jq -er '.version'`
  exits 0 (Harbor disables the token, so the API is reachable unauthenticated).

### F2. chatui

- Ready: container `harbor.chatui-db` healthy, then 200 probe on
  `$(./harbor.sh url chatui)/` (≤300 s).
- Function: front page serves the SPA:
  `curl -s "$(./harbor.sh url chatui)/" | grep -qi '<html'` exits 0.

### F3. librechat

- Ready: 200 probe on `$(./harbor.sh url librechat)/` (≤300 s; five
  containers: app, mongo, meilisearch, pgvector, rag).
- Function: `curl -s "$(./harbor.sh url librechat)/api/config" | jq -er '.appTitle'`
  exits 0 (unauthenticated config endpoint).

### F4. promptfoo

- Ready: 200 probe on `$(./harbor.sh url promptfoo)/` (≤120 s).
- Function: `curl -s "$(./harbor.sh url promptfoo)/health" | jq -er '.status'`
  exits 0 (server health endpoint; if the path differs in a newer image,
  a 200 on `/` with an `<html` body is the fallback PASS).

Teardown: `./harbor.sh down`

## Group G — container CLIs batch 2 (fabric, cmdh) via ollama

Both are run-style containers (like aichat/gptme): never include them in
`harbor up`; invoke via their dedicated `harbor fabric` / `harbor cmdh`
subcommands, which `docker compose run` the container with the active
backend's overlay.

Pre: `./harbor.sh up ollama`; wait for D1 readiness;
`./harbor.sh exec ollama ollama pull qwen3:0.6b`.

### G1. fabric

- Pre: save current value, then `./harbor.sh config set fabric.model qwen3:0.6b`
  (shipped default `qwen3.5:4b` is not pulled); restore afterwards.
- Function:
  `echo 'Reply with exactly: PONG' | timeout 300 ./harbor.sh fabric`
  Expected: exit 0, non-empty stdout with model output (fabric sends raw
  stdin to the default vendor/model — Ollama via the
  compose.x.fabric.ollama.yml overlay).

### G2. cmdh

- Pre: save current value, then `./harbor.sh config set cmdh.model qwen3:0.6b`;
  restore afterwards. Default host is `ollama`
  (`cmdh.llm.host`), so only the model needs overriding.
- Function:
  `timeout 300 ./harbor.sh cmdh 'print the current directory' </dev/null`
  Expected: exit 0 (or clean non-interactive exit), stdout contains a
  generated shell command (e.g. `pwd`). cmdh prompts to run the command;
  with stdin closed it must not hang — if it does, treat the printed
  suggestion before the prompt as the functional evidence and kill via
  timeout, recording the observed behavior.

Teardown: `./harbor.sh down`; remove any leftover
`harbor.fabric` / `harbor.cmdh-cli` run containers.

## Group H — batch 3 web/API services (kobold, speaches, txtairag, plandex, webtop)

All five are up-style containers with prebuilt images (webtop builds a thin
Dockerfile layer). Run in two sub-batches to bound downloads/RAM, `down`
between them. All are CPU-friendly.

### H-a: kobold + speaches

Pre: `./harbor.sh up kobold speaches` (also brings up default services).

#### H1. kobold (koboldcpp)

- Downloads its default model on first start
  (`HARBOR_KOBOLD_MODEL` — KobbleTiny-Q4_K, ~670 MB); allow up to 10 min.
- Ready: 200 on `$(./harbor.sh url kobold)/api/v1/model` and the response
  names the loaded model (non-empty `result`).
- Function: `curl -s $URL/api/v1/generate -d '{"prompt":"Reply with exactly: PONG\n","max_length":16}'`
  → HTTP 200, JSON `.results[0].text` non-empty.

#### H2. speaches (STT/TTS)

- The `speaches-init` sidecar registers/downloads the STT model
  (`Systran/faster-distil-whisper-small.en`) and TTS model (Kokoro int8);
  wait for `harbor.speaches-init` to exit 0 (allow up to 10 min).
- Ready: `curl -s $(./harbor.sh url speaches)/health` → 200.
- Registry: `curl -s $URL/v1/models` lists the STT model id.
- Function (round trip): POST `/v1/audio/speech`
  (`{"model": <tts>, "voice": "af_bella", "input": "hello world", "response_format": "wav"}`)
  → non-empty wav; then POST that wav to `/v1/audio/transcriptions`
  (multipart, `model=<stt>`) → 200, JSON `.text` contains "hello"
  (case-insensitive). If TTS model fails to provision, fall back to STT-only
  on any wav with 200 + valid JSON as the pass bar, recording why.

Teardown: `./harbor.sh down`.

### H-b: txtairag + plandex + webtop

Pre: `./harbor.sh up txtairag plandex webtop` (plandex CLI container is
run-style — expect `plandex-server` + `plandex-db` up; webtop builds its
image on first up).

#### H3. txtairag

- Startup-only: Streamlit downloads the wiki-slim embeddings index on first
  request; check 200 on `$(./harbor.sh url txtairag)/` within 300 s and
  `/healthz` (Streamlit health) returns `ok`. Full RAG query needs the
  qwen3.5:4b LLM via ollama overlay — out of scope for CPU batch.

#### H4. plandex

- Ready: `curl -s $(./harbor.sh url plandex-server)/health` → 200
  (`harbor url plandex` fails once the run-style CLI container exits)
  within 300 s (first boot does fresh postgres init + LiteLLM proxy
  bootstrap + migrations before the listener opens). If `/health` is not the path, discover via
  `docker logs harbor.plandex-server` and record the actual endpoint.

#### H5. webtop

- Ready: 200 on `$(./harbor.sh url webtop)/` within 300 s (KDE web desktop
  login page; selkies/kasmVNC serves HTTP on 3000).

Teardown: `./harbor.sh down`; verify no `harbor.*` containers remain.

## Group I — depth + integrations of covered services (Batch I of the Coverage Plan)

Four serial sub-batches; automated in `tests/services-integration.sh --groups I`.

### I-a: webui chat, searxng categories, litellm proxy, boost modules

Pre: `harbor config set boost.modules "klmbr;rcn;g1;mcts;eli5;concept;ponder"`
(boost only serves configured modules; restore afterwards), then
`./harbor.sh up llamacpp webui boost litellm searxng`.

#### I1. webui chat round trip

- Signup a throwaway user via `POST /api/v1/auths/signup` → token. Existing
  instances have users, so the new user lands as `pending`: promote it to
  `admin` directly in `/app/backend/data/webui.db` inside the container.
- `POST /api/chat/completions` with `Bearer <token>`, `model=$MODEL`,
  `max_tokens 2000` → non-empty `.choices[0].message.content`.
- Cleanup: delete the test user from `user` and `auth` tables.

#### I2. searxng category queries

- `GET /search?q=github&categories=images&format=json` and
  `...&categories=it&format=json` → `.results` is an array (result counts vary
  with external engine availability; the JSON category path itself must work).

#### I3. litellm actually proxying

- Ships via the new `services/litellm/litellm.llamacpp.yaml` +
  `services/compose.x.litellm.llamacpp.yml` (wildcard routing — the llama.cpp
  router auto-discovers models, so no static id can be pinned).
- `GET /v1/models` (master key) → `.data | length > 0`.
- `POST /v1/chat/completions` with `model=llamacpp/$MODEL` → non-empty content.

#### I4. boost modules (7-module sample)

- For each of klmbr, rcn, g1, mcts, eli5, concept, ponder: find the
  `<module>-<model>` id in `/v1/models` (Bearer sk-boost) and get a non-empty
  completion (`-m 900` — multi-turn modules like mcts/rcn/g1 make many
  internal calls on CPU). One retry per module.
- rcn and g1 capture the *content* of intermediate completions into the chat;
  thinking models (Qwen3.5) return only `reasoning_content` there, producing
  empty assistant turns and an empty final answer — use the non-thinking,
  template-tolerant model (LFM2.5) for those two; the rest use `$MODEL`.
- Product defect found here (fact cvg): g1 appends multiple consecutive
  assistant messages, which llama.cpp rejects with 400 "Cannot have 2 or more
  assistant messages at the end of the list". Fixed by merging consecutive
  same-role plain messages in `ChatNode.history()` (tool messages exempt).

### I-b: jupyter kernel execution, promptfoo eval

Pre: `./harbor.sh up ollama jupyter promptfoo`; pull `qwen3:0.6b`.

#### I5. jupyter kernel execute

- `docker exec harbor.jupyter python -c '<jupyter_client start_new_kernel;
  execute print(6*7); read iopub stream>'` → `42`.

#### I6. promptfoo eval run

- Inside the container (with `OLLAMA_BASE_URL=http://ollama:11434`): write a
  minimal config (one prompt, provider `ollama:chat:qwen3:0.6b`, a
  `javascript: output.length > 0` assert) to `/tmp/pf.yaml` and run
  `promptfoo eval -c pf.yaml` (fallback `node /app/dist/src/main.js`).
  Exit 0 = eval executed and assertion passed.

### I-c: comfyui workflow submission (CPU)

Pre: `harbor config set comfyui.args "--cpu"` + recreate (Group E workaround).

#### I7. comfyui workflow

- `POST /prompt` with a model-free graph `EmptyImage → SaveImage` → `prompt_id`;
  poll `GET /history/<prompt_id>` until `.outputs | length > 0` (≤120 s).
  Exercises queueing, execution, and history without checkpoints.

### I-d: chatui/librechat chat round trips, langflow flow execution

Pre: `./harbor.sh up llamacpp ollama chatui librechat langflow`; pull
`qwen3:0.6b` into ollama.

#### I8. chatui chat round trip

- chat-ui >= 0.10 dropped the `MODELS` env list for a single OpenAI-compatible
  provider (`OPENAI_BASE_URL`/`OPENAI_API_KEY`); models are discovered from
  its `/models` endpoint. Harbor's `envify.js` bridges the legacy per-backend
  `MODELS` configs to the new scheme using the first configured endpoint
  (product defect found here: without the bridge, chatui silently ignored
  Harbor's config and served HuggingFace's default router catalog).
- chatui sends no `max_tokens`, so a thinking model (Qwen3.5) can ramble to
  context exhaustion (observed: 74k+ tokens decoded, request never returns) —
  use the non-thinking template-tolerant model (LFM2.5, same as opencode/rcn/g1).
- `POST /conversation` (JSON `{"model": "<LFM2.5 router id>"}`) → mints the
  anonymous `hf-chat` session cookie and returns `conversationId` +
  `rootMessageId`.
- `POST /conversation/<id>` — multipart field `data` with
  `{"inputs": ..., "id": "<rootMessageId>", "is_retry": false,
  "is_continue": false, "web_search": false, "tools": []}`. Requires an
  `Origin` header matching the service URL ("Non-JSON form requests need to
  have an origin" otherwise). Streams until `{"status":"finished"}`.
- `GET /api/v2/conversations/<id>` → assistant message `content` non-empty.

#### I9. librechat chat round trip

- Registration is disabled by default (`Registration is not allowed.`), so
  seed the test user via the bundled script:
  `docker exec harbor.librechat node /app/config/create-user.js <email> <name>
  <username> <password> --email-verified=true`.
- `POST /api/auth/login` → `.token`.
- Chat needs: a browser-like `User-Agent` (the uaParser middleware answers
  `Illegal request` to anything ua-parser-js does not recognize as a browser),
  one `GET /api/models` to warm the endpoint model cache
  (`endpoint_models_not_loaded` otherwise), and endpoint name `ollama` in
  lowercase (the custom endpoint named "Ollama" is normalized to the known
  ollama type; the literal name fails with `Unknown endpoint`).
- `POST /api/agents/chat/ollama` with `{"text": ..., "endpoint": "ollama",
  "endpointType": "custom", "model": "qwen3:0.6b", "conversationId": null,
  "parentMessageId": "00000000-0000-0000-0000-000000000000",
  "isCreatedByUser": true, ...}` → returns `conversationId` immediately;
  poll `GET /api/messages/<cid>` until a non-user message has text (top-level
  `.text` or `content[]` entries of type `text` — reasoning models put the
  reply only in the content array) (≤300 s).
- Product defect found here: `librechat.yml` set the Ollama endpoint baseURL
  to `.../v1/chat/completions`; LibreChat's (langchain-based) client appends
  `/chat/completions` itself → 404. Fixed to `.../v1`.
- Cleanup: `db.users.deleteOne` via mongosh in harbor.librechat-db (the
  interactive delete-user script hangs without a TTY).

#### I10. langflow flow execution

- Auth: `GET /api/v1/auto_login` → `access_token` (Harbor ships
  `LANGFLOW_AUTO_LOGIN=true`). Note some endpoints gzip regardless of
  `Accept-Encoding`.
- `tests/lib/langflow-flow.py` builds a minimal ChatInput → ChatOutput
  passthrough flow using node templates taken from the live
  `GET /api/v1/all` catalog (so it tracks the installed component versions),
  imports it via `POST /api/v1/flows/`, mints an API key via
  `POST /api/v1/api_key/` (the run API 403s on the JWT alone), executes
  `POST /api/v1/run/<flow_id>` with `input_value=PONG-services-it`, asserts
  the chat output echoes the input exactly, and deletes the flow.
- A pure passthrough is used deliberately: it exercises flow import, graph
  validation, execution, and the run API without pinning an LLM component
  schema; LLM-backed flows are covered by other checks.

Teardown after each sub-batch: `./harbor.sh down` + config restore.

## Group J — ROCm/GPU paths (Batch J of the Coverage Plan)

AMD-GPU-only group; automated in `tests/services-integration.sh --groups J`
but **excluded from the default group list**. The runner gates the whole group
behind host ROCm detection (same predicate as `harbor.sh has_rocm`: `/dev/kfd`
exists, `/dev/dri/renderD*` exists, `amdgpu` kernel module loaded) and SKIPs
every check cleanly on non-ROCm hosts.

How Harbor selects ROCm variants: `services/compose.x.<svc>.rocm.yml` are
*capability* overlay files — `harbor.sh` auto-includes them when `has_rocm()`
passes (no config flag needed). The overlays pass `/dev/kfd` + `/dev/dri` into
the container and switch the image/env: llamacpp → `HARBOR_LLAMACPP_IMAGE_ROCM`,
ollama → `${HARBOR_OLLAMA_IMAGE}:rocm`, localai →
`${HARBOR_LOCALAI_IMAGE}:${HARBOR_LOCALAI_ROCM_VERSION}` (latest-gpu-hipblas),
lemonade → `LEMONADE_LLAMACPP=rocm`, vllm/voicebox → devices only.

Groups run serially, one service at a time (they contend for the iGPU).

### J1. llamacpp.rocm

- `./harbor.sh up llamacpp` → container uses `$HARBOR_LLAMACPP_IMAGE_ROCM`
  with `/dev/kfd` + `/dev/dri` (docker inspect).
- `docker logs harbor.llamacpp` contains a `ROCm0` device line (e.g.
  `ROCm0 : AMD Radeon 8060S Graphics`).
- Chat completion with `$MODEL` returns non-empty content (GPU-fast: ~4 s
  where the CPU path needs ~30 s+).
- Note: this host overrides `llamacpp.image_rocm` to
  `kyuz0/amd-strix-halo-toolboxes` (Strix Halo build); the check is
  image-agnostic — it only asserts ROCm device init + inference.

### J2. ollama.rocm

- `./harbor.sh up ollama` → image `ollama/ollama:rocm`, devices passed.
- Logs contain `library=ROCm` on the `inference compute` line
  (e.g. `compute=gfx1151 name=ROCm0`).
- Pull `qwen3:0.6b`, `/api/generate` non-empty; `ollama ps` shows
  `100% GPU`. Observed 228 tok/s eval on gfx1151.

### J3. lemonade

- `./harbor.sh up lemonade` → container env `LEMONADE_LLAMACPP=rocm` (overlay
  wins over the `cpu` default), devices passed; `/live` 200.
- `/api/v1/system-info` reports the rocm llamacpp backend `state: installed`
  with device `amd_gpu` (backend binaries ship in the image).
- Register the cached GGUF (HF cache is mounted):
  `POST /api/v1/pull {"model_name":"user.qwen-tiny","checkpoint":"unsloth/Qwen3.5-0.8B-GGUF:Q4_K_M","recipe":"llamacpp"}`
  → status success, no download.
- Chat completion on `user.qwen-tiny` returns non-empty content or
  reasoning_content (thinking model; use max_tokens 4000). Logs show
  `ROCm0 model buffer` lines.
- **Do NOT clean up with `POST /api/v1/delete`**: lemonade's delete removes
  the checkpoint files from the shared HF cache (observed: it deleted
  `Qwen3.5-0.8B Q4_K_M`, which the llamacpp router and other groups' model
  discovery then lost). Registration is idempotent; leave it in place.

### J4. localai.rocm

- `./harbor.sh up localai` → image tag `latest-gpu-hipblas` (~4.3 GB
  compressed pull on first run), devices passed; `/readyz` 200.
- Install a small model from the gallery: `POST /models/apply {"id":"qwen3-0.6b"}`,
  poll `/v1/models` until listed. First model load also auto-installs the
  `rocm-hipblas-llama-cpp` OCI backend (~3.1 GB) — GPU-detected selection is
  itself the ROCm evidence, along with `n_gpu_layers=99999999` in the load
  line and non-zero `rocm-smi` GPU use during generation.
- Chat completion returns non-empty content (~3.5 s observed).
- The runner gives J4 generous timeouts (first run downloads ~8 GB total).

### J5. voicebox (startup + device check only)

- `./harbor.sh up voicebox` (git build on first run) → devices `/dev/kfd`,
  `/dev/dri` and `group_add: video` present; `/health` 200.
- **Documented limitation, not a defect fixed here**: the upstream voicebox
  Dockerfile installs CPU-only PyTorch (`torch.version.hip = None`), so
  `/health` reports `"gpu_available": false, "backend_variant": "cpu"` even
  with the devices passed. The `compose.x.voicebox.rocm.yml` overlay is
  currently ineffective beyond device passthrough; GPU support needs a
  ROCm-torch image upstream. J5 asserts startup + devices only.

### J6. vllm.rocm (manual image switch; SKIPped unless configured)

- The default `HARBOR_VLLM_IMAGE=vllm/vllm-openai` is a **CUDA build** — the
  rocm overlay passes devices but the stock image cannot init HIP. The runner
  SKIPs J6 when `vllm.image` is still the default.
- Verified procedure on this host (2026-07-20):
  `harbor config set vllm.image kyuz0/vllm-therock-gfx1151`,
  `vllm.version stable`, `vllm.model Qwen/Qwen3-0.6B`,
  `vllm.model_specifier "--model Qwen/Qwen3-0.6B"`,
  `vllm.extra_args "--max-model-len 4096 --gpu-memory-utilization 0.35"`,
  `harbor build vllm`, `harbor up vllm` → health 200 in ~140 s, logs show
  ROCm attention backend selection (`rocm.py … ROCM_ATTN`), completion in
  ~4.8 s. Restore all five config keys afterwards.
- When configured with a non-default image, the runner runs health +
  completion checks.

Teardown after each check: `./harbor.sh down`.

## Group K — lightweight standalone CPU web services (Batch K of the Coverage Plan)

Automated in `tests/services-integration.sh --groups K`; part of the default
group list (CPU-safe, no LLM backend required). All eight services start
concurrently (`harbor up landing hollama mikupad mock-openai qdrant
libretranslate netdata dbhub`) — distinct ports, no GPU contention.

Batch K remainder (deferred to a later iteration): drawio, sillytavern,
lobechat, traefik (traefik needs a routed target service — an integration
check, not standalone).

### K1. landing

- Ready: `GET /` returns 200 within 120 s.
- Functional: index body contains `harbor` (case-insensitive); `GET /docs/`
  serves the autoindexed docs mount (body contains `href`).

### K2. hollama

- Ready: `GET /` returns 200 within 120 s.
- Functional: SPA index body contains `hollama` (it is a static frontend for
  ollama; deeper interaction requires a browser session — content check is
  the deepest headless assertion available).

### K3. mikupad

- Image builds from `github.com/lmg-anon/mikupad#main` at `harbor up` (first
  run compiles the image); allow 300 s ready window.
- Functional: served single-file app contains `mikupad`.

### K4. mock-openai

- Harbor's own OpenAI-shaped test fixture (`tests/fixtures/mock-openai`).
- Ready: `GET /v1/models` 200; `.data[0].id == "mock-model"`.
- Functional: `POST /v1/chat/completions` returns non-empty
  `.choices[0].message.content` ("Hello from mock-openai!").

### K5. qdrant

- Auth: all requests need `api-key: $(harbor config get qdrant.api_key)`.
- Ready: `GET /healthz` 200 within 120 s.
- Functional (CRUD round trip): `PUT /collections/harbor_it_k5` (vectors
  size 4, Dot) → `.result == true`; upsert 2 points (`?wait=true`); search
  with vector `[0.9,0.1,0.1,0.1]` limit 1 → top hit `id == 2`; delete the
  collection afterwards.

### K6. libretranslate

- Pre-step: `harbor env libretranslate LT_LOAD_ONLY en,es` — the default
  (`LT_UPDATE_MODELS=true`, no load-only filter) downloads every language
  pair (~10 GB). Unset after the run.
- Ready: `GET /languages` 200 within 600 s (en/es models download on first
  boot).
- Functional: `POST /translate {"q":"hello world","source":"en","target":"es"}`
  → `.translatedText` non-empty and different from the input ("Hola mundo").

### K7. netdata

- Ready: `GET /api/v1/info` 200 within 180 s.
- Functional: `.version` non-empty from the same endpoint (real metrics API,
  not a static page).

### K8. dbhub

- MCP server (streamable HTTP transport) — Harbor entrypoint falls back to
  `--demo` (bundled sample SQLite) when `DSN` is empty, so it works out of
  the box.
- Endpoint is `POST /mcp` (stateless streamable HTTP — plain JSON responses,
  no session header required); `Accept: application/json, text/event-stream`
  must be sent.
- Functional: JSON-RPC `initialize` returns `.result.serverInfo.name`
  ("DBHub MCP Server"; polled up to 120 s), then `tools/call` of
  `execute_sql` with `SELECT 6*7 AS answer` returns rows `[{"answer":42}]`
  (nested as JSON text in `.result.content[0].text`).

Teardown: `./harbor.sh down` + `harbor env libretranslate unset LT_LOAD_ONLY`.

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

### Run 2026-07-20 — Group B

CHECK: B1 searxng ready
COMMAND: 200 probe on `$(./harbor.sh url searxng)/`
EXPECTED: 200 within 120 s
ACTUAL: first `harbor up` failed — container crash-looped on boot; after fixes, `Up (healthy)`, probe 200
RESULT: PASS — after two product-defect fixes in `services/searxng/settings.yml`: (1) typo `requires_api_key` (vs `require_api_key`) in the gpodder engine, rejected by current image's strict about-schema validation; (2) the whole shipped settings.yml was stale vs `searxng/searxng:latest` (2026.7.19) — next crash `mojeek language_support should be set to True`. Regenerated settings.yml from the image's own `settings.yml.new`, re-applying Harbor deltas (instance_name `searxng`, `json` in search.formats, existing secret_key). Fact 5b8.

CHECK: B1 searxng JSON search
COMMAND: `curl -s "$URL/search?q=harbor&format=json" | jq -er '.results | type == "array"'`
EXPECTED: `true`, exit 0
ACTUAL: `true`, exit 0
RESULT: PASS

CHECK: B2 langflow ready
COMMAND: 200 probe on `$(./harbor.sh url langflow)/health`
EXPECTED: 200 within 300 s
ACTUAL: first boot Exited(1): `PermissionError: /var/lib/langflow/secret_key` — Docker created the `services/langflow/data` bind mount root:root; langflow runs as uid 1000. After fix, probe 200 in <60 s
RESULT: PASS — product defect fixed: added `langflow-init` chown sidecar (services/compose.langflow.yml + services/langflow/workspace-init.sh), mirroring the kotaemon/unsloth-studio/beszel pattern. Fact fqo.

CHECK: B2 langflow version
COMMAND: `curl -s "$URL/api/v1/version" | jq -er '.version'`
EXPECTED: exit 0
ACTUAL: `1.10.2`, exit 0
RESULT: PASS

Teardown: `./harbor.sh down` executed.

### Run 2026-07-20 — Group C

Pre: `./harbor.sh up llamacpp`; health 200; `MODEL=unsloth/Qwen3.5-0.8B-GGUF:Q4_K_M`.

CHECK: C1 hermes one-shot
COMMAND: `timeout 300 ./harbor.sh launch --backend llamacpp --model "$MODEL" hermes -z "Reply with exactly: PONG and nothing else" </dev/null` (hermes' non-interactive flag is `-z PROMPT`)
EXPECTED: exit 0, non-empty model output
ACTUAL: exit 0, stdout `PONG`
RESULT: PASS

CHECK: C2 opencode run
COMMAND: `timeout 600 ./harbor.sh launch --backend llamacpp --model 'LiquidAI/LFM2.5-8B-A1B-GGUF:Q8_0' opencode run "Reply with exactly: PONG and nothing else" </dev/null`
EXPECTED: exit 0, output contains model reply
ACTUAL: exit 0, stdout ends with `PONG`
RESULT: PASS — after spec fix: with `$MODEL` (Qwen3.5) llama.cpp returned 400 "Jinja Exception: System message must be at the beginning" during automatic tool-parser generation, because opencode sends a non-first system message and Qwen3.5's template raises on it (reproduced with bare curl: `[user, system]` message order 400s; tools alone are fine). Not a Harbor defect — upstream opencode/model-template interaction; spec updated to use a template-tolerant model and to assert on output (opencode run exits 0 even on API errors).

Triage summary Group B+C: two real product defects fixed (searxng stale/typo'd settings.yml — fact 5b8; langflow first-boot bind-mount ownership — fact fqo, init-sidecar pattern). One bad spec expectation fixed (C2 model choice + exit-code assertion). No environment-only failures.

Teardown: `./harbor.sh down` executed.

### Run 2026-07-20 — Group D

CHECK: D1 ollama ready
COMMAND: `curl -s "$(./harbor.sh url ollama)/api/version" | jq -er '.version'`
EXPECTED: exit 0 within 120 s
ACTUAL: `0.22.1` immediately after `harbor up ollama` reported healthy
RESULT: PASS

CHECK: D1 ollama pull + generate
COMMAND: `./harbor.sh exec ollama ollama pull qwen3:0.6b`; then `curl -s "$URL/api/generate" -d '{"model":"qwen3:0.6b","prompt":"Reply with exactly: PONG","stream":false}' | jq -er '.response | length > 0'`
EXPECTED: pull exit 0; jq prints `true`
ACTUAL: pull `success`, exit 0; jq `true`
RESULT: PASS

CHECK: D2 gptme one-shot
COMMAND: `timeout 300 ./harbor.sh gptme -n --no-stream 'Reply with exactly: PONG' </dev/null` (after `harbor config set gptme.model qwen3:0.6b`)
EXPECTED: exit 0, non-empty stdout with model output
ACTUAL: exit 0; model produced thinking + reply; gptme auto-reply loop asked for tool calls twice, then exited cleanly ("Autonomous mode: No tools used after 2 confirmations")
RESULT: PASS — after two spec fixes: (1) `harbor run gptme` is the wrong entrypoint — only the `harbor gptme` subcommand injects `-m local/<gptme.model>`, without it gptme has no model; (2) gptme must not be in the `harbor up` list (run-style container, same as aichat). Also gptme.model must be a model that actually exists in ollama (default `qwen3.5:4b` is not pulled by D1) — check now sets/restores it.

Triage summary Group D: no product defects. Two bad spec expectations fixed (gptme invocation via subcommand, not `harbor run`; run-style container excluded from `up`). Config note: gptme.model must match a pulled ollama tag. Teardown: `./harbor.sh down`; gptme.model restored to `qwen3.5:4b`.

### Run 2026-07-20 — Group E

Host: AMD (Strix Halo), no NVIDIA driver.

CHECK: E1 comfyui ready
COMMAND: 200 probe on `$(./harbor.sh url comfyui)/`
EXPECTED: 200 within 300 s
ACTUAL: first attempt (default config): container `Up`, init sidecar exit 0, ports bound, but probe stayed 000 for 300 s — ComfyUI process FATAL in supervisor: `RuntimeError: Found no NVIDIA driver on your system` (image is `latest-cuda`; environment limitation, not a Harbor defect). Retry with `harbor config set comfyui.args "--cpu"` and container recreate: probe 200 in ~20 s
RESULT: PASS (CPU mode) — environment note recorded in the Group E preamble; a `docker restart` is not enough after changing comfyui.args, the container must be recreated (`docker rm -f harbor.comfyui && harbor up comfyui`) since env is read at create time. `harbor up` also refuses to recreate while the old container holds its own ports — remove it first.

CHECK: E1 comfyui system_stats
COMMAND: `curl -s "$URL/system_stats" | jq -er '.system'`
EXPECTED: exit 0
ACTUAL: exit 0 — `comfyui_version v0.2.2`, device type `cpu`
RESULT: PASS

### Run 2026-07-20 — Group F

CHECK: F1 jupyter ready + version
COMMAND: 200 probe on `$(./harbor.sh url jupyter)/api`; `curl -s $URL/api | jq -er '.version'`
EXPECTED: 200 ≤600 s; version string
ACTUAL: 200 on first poll; `2.20.0`
RESULT: PASS (image was already built locally; first-time builds pull the large PyTorch base)

CHECK: F2 chatui front page
COMMAND: 200 probe on `$(./harbor.sh url chatui)/`; `curl -s $URL/ | grep -qi '<html'`
EXPECTED: 200; HTML body
ACTUAL: 200 on first poll; `<html` present
RESULT: PASS

CHECK: F3 librechat ready + config API
COMMAND: 200 probe on `$(./harbor.sh url librechat)/`; `curl -s $URL/api/config | jq -er '.appTitle'`
EXPECTED: 200 ≤300 s; app title
ACTUAL: first `harbor up` FAILED — `harbor.librechat-rag` Exited(1): pgvector connection refused at import time (rag raced `librechat-vector`, which had no healthcheck; rag had bare `depends_on` and no restart policy). After fix: all 5 containers Up, probe 200, `LibreChat`
RESULT: PASS — product defect fixed in `services/compose.librechat.yml`: added `pg_isready` healthcheck to librechat-vector and gated librechat-rag with `depends_on: condition: service_healthy`. Fact 183.

CHECK: F4 promptfoo ready + health
COMMAND: 200 probe on `$(./harbor.sh url promptfoo)/`; `curl -s $URL/health | jq -er '.status'`
EXPECTED: 200 ≤120 s; status string
ACTUAL: 200 on first poll; `{"status":"OK","version":"0.121.11"}`
RESULT: PASS

Teardown: `./harbor.sh down` executed; no containers left.

### Run 2026-07-20 — Group G

Pre: `./harbor.sh up ollama`; `ollama pull qwen3:0.6b` → success.

CHECK: G1 fabric one-shot
COMMAND: `echo 'Reply with exactly: PONG' | timeout 300 ./harbor.sh fabric` (after `harbor config set fabric.model qwen3:0.6b`)
EXPECTED: exit 0, model output on stdout
ACTUAL: first run FAILED — `error loading .env file: open /home/appuser/.config/fabric/.env: no such file or directory`, exit 1. Two causes: (1) `compose.fabric.yml` mounted the config to `/root/.config/fabric` but current `ghcr.io/ksylvan/fabric` runs as `appuser` (uid 1000, home `/home/appuser`); (2) fabric hard-fails when `~/.config/fabric/.env` is missing even with vendor/model set via environment. After fix: exit 0, stdout `PONG`
RESULT: PASS — product defect fixed in `services/compose.fabric.yml`: mount target changed to `/home/appuser/.config/fabric` and entrypoint touches `.env` before exec'ing fabric. Fact us5. (One transient ghcr.io pull timeout retried — environment, not a defect.)

CHECK: G2 cmdh one-shot
COMMAND: `timeout 300 ./harbor.sh cmdh 'print the current directory' </dev/null` (after `harbor config set cmdh.model qwen3:0.6b`)
EXPECTED: exit 0 (or clean non-interactive exit), stdout contains a generated command
ACTUAL: first run FAILED — `Error: invalid JSON schema in format` from the ollama client. Root cause: `services/cmdh/Dockerfile` installs unpinned `zod` (now v4) while `zod-to-json-schema` v3 only understands zod v3 internals — it silently emitted `{"$schema": "..."}` (empty schema), which Ollama rejects. After fix: exit 0; `desired command: pwd`, assistant message present, option prompt exits cleanly on closed stdin
RESULT: PASS — product defect fixed: `services/cmdh/ollama.ts` now passes a literal JSON schema as `format` (zod/zod-to-json-schema dropped from the adapter and Dockerfile). Fact iqb.

Triage summary Groups F+G: three real product defects fixed (librechat-rag startup race — fact 183; fabric config mount vs image user + missing-.env hard fail — fact us5; cmdh empty structured-output schema from zod v3/v4 mismatch — fact iqb). One dev-tooling fix: lint file collector now skips service runtime dirs (workspace/vectordb/meili_data*) that crashed the strict scan — fact nal. No bad spec expectations. Teardown: `./harbor.sh down`; fabric.model and cmdh.model restored to `qwen3.5:4b`.

Triage summary Group E: no product defects. One environment limitation (CUDA-only default image on a non-NVIDIA host) with a documented config workaround (`comfyui.args "--cpu"`). Teardown: `./harbor.sh down`; comfyui.args restored to empty.

### Run 2026-07-20 — Group H-a (kobold, speaches)

Pre: `./harbor.sh up kobold speaches` — all containers Up, `speaches-init` Exited (0).

CHECK: H1 kobold ready + generate
COMMAND: `curl $URL/api/v1/model`; `curl $URL/api/v1/generate -d '{"prompt":"Reply with exactly: PONG\n","max_length":16}'`
EXPECTED: model name non-empty; 200 with non-empty `.results[0].text`
ACTUAL: `{"result": "koboldcpp/KobbleTiny-Q4_K"}`; generate 200, `.results[0].text` non-empty (base completion model rambles rather than obeying — expected for a 1.1B base model; non-empty text is the bar)
RESULT: PASS

CHECK: H2 speaches health + registry + TTS→STT round trip
COMMAND: `curl $URL/health`; `curl $URL/v1/models`; POST `/v1/audio/speech` (Kokoro int8, af_bella, "hello world", wav) then POST the wav to `/v1/audio/transcriptions` (Systran/faster-distil-whisper-small.en)
EXPECTED: 200; STT model listed; transcription text contains "hello"
ACTUAL: health 200; models list both `speaches-ai/Kokoro-82M-v1.0-ONNX-int8` and `Systran/faster-distil-whisper-small.en`; TTS 200 → 42 KB RIFF wav; STT → `{"text":"Hello world."}`
RESULT: PASS

Teardown: `./harbor.sh down`; no containers left.

### Run 2026-07-20 — Group H-b (txtairag, plandex, webtop)

Pre: `./harbor.sh up txtairag plandex webtop`. First attempts FAILED on four
independent product defects (fixed below) before all services came up.

CHECK: H3 txtairag Streamlit up
COMMAND: 200 probe on `$(harbor url txtairag)/` and `/healthz`
EXPECTED: 200 within 300 s; healthz 200
ACTUAL: 200 on first poll after start; `/healthz` 200 (Streamlit serves the SPA shell on both paths)
RESULT: PASS

CHECK: H4 plandex server health
COMMAND: `curl $(harbor url plandex)/health`
EXPECTED: 200 within 120 s
ACTUAL: three defects on the way: (1) CLI image build failed — `plandex.ai` domain is NXDOMAIN, `wget https://plandex.ai/install.sh` exit 1, and the repo installer also resolves its version from plandex.ai (curl exit 6); (2) `ghcr.io/wipash/plandex:rolling` server crashed in a loop — its embedded LiteLLM launch dies on `No module named uvicorn` (broken third-party image); (3) `- /etc/timezone:/etc/timezone:ro` mount failed on Fedora ("not a directory": docker had created the missing host path as a directory); (4) `postgres` (unpinned → 18) refused the `/var/lib/postgresql/data` mount layout. After fixes: `OK`, 200 in <15 s
RESULT: PASS — fixes: Dockerfile fetches the installer from GitHub raw and derives PLANDEX_VERSION from the latest `cli/v*` release (fact 2vy); server image switched to official `plandexai/plandex-server:latest` listening on 8099 in development mode — port mapping + `PLANDEX_API_HOST` updated (facts 843, zn5); `/etc/timezone` mounts dropped, `/etc/localtime` kept (fact nre); db pinned `postgres:17` (fact m3u). Note: the `plandex` CLI container is run-style and exits at its interactive auth prompt without a TTY — a fresh `harbor up plandex` may report failure on that container even when server+db are healthy.

CHECK: H5 webtop desktop up
COMMAND: 200 probe on `$(harbor url webtop)/`
EXPECTED: 200 within 300 s
ACTUAL: image build FAILED twice first: `neofetch` no longer exists in the Ubuntu base (apt exit 100), and the legacy `npmjs.org/install.sh` npm bootstrap is defunct (exit 1; distro `nodejs`+`npm` also mutually conflict in this base). After fixes (drop neofetch — fact dfh; NodeSource node 22 which bundles npm — fact uv2): build OK, 200 on first poll
RESULT: PASS

### Run 2026-07-20 — Groups A + G (re-execution, fresh context)

`MODEL=unsloth/Qwen3.5-0.8B-GGUF:Q4_K_M`.

CHECK: A1 ready — health 200 on first poll — PASS.
CHECK: A1 chat completion — first attempt `false` (reasoning consumed all 2000 tokens, empty content — intermittent for this thinking model), re-run `true` (content `PONG`, 160 completion tokens) — PASS (flaky-once).
CHECK: A2 webui — `healthy`, `/health` 200, version `0.9.6` — PASS.
CHECK: A3 boost — health 200; models `true`; boosted completion via `autotemp-...` `true`; no-auth 401 — PASS (all four).
CHECK: A4 litellm — liveliness 200; models `[]` exit 0 (expected, no llamacpp overlay) — PASS.
CHECK: A5 aichat — first two attempts timed out with runaway generation; removing `harbor-aichat-run-*` did NOT free the llamacpp slot (orphaned task kept decoding to 93k tokens) — required `docker restart harbor.llamacpp`; clean retry rc=0, output ends `PONG` — PASS. Spec updated (reproducibility fix): retry procedure now says to restart llamacpp, not just remove containers.
CHECK: G1 fabric — rc=0, stdout `PONG` (fabric.model=qwen3:0.6b, restored after) — PASS.
CHECK: G2 cmdh — rc=0, `desired command: pwd` + assistant message, option prompt exits cleanly on closed stdin (cmdh.model=qwen3:0.6b, restored after) — PASS.

Triage: no product defects. One reproducibility gap fixed in A5 retry guidance. Teardown `./harbor.sh down`; aichat/fabric/cmdh models restored to `qwen3.5:4b`; no containers left.

Triage summary Group H: six real product defects fixed across plandex (installer domain dead, broken third-party server image, port drift, fragile /etc/timezone mount, unpinned postgres hitting the PG18 layout change) and webtop (removed apt package, defunct npm bootstrap). No Harbor defects in kobold/speaches/txtairag. Teardown: `./harbor.sh down`; no config overrides were changed in this group; stale root-owned runtime dirs removed via alpine before linting.

## Coverage Plan (extension)

Gap analysis of 2026-07-20 (host: AMD Strix Halo — ROCm iGPU, no NVIDIA, no external API keys). 23 services covered by Groups A–H; ~108 top-level services remain uncovered (sidecars like `*-db`/`*-init` counted with their parent). Classification below is verified against `services/compose.<name>.yml` and `services/compose.x.*.yml` overlays, not guessed; borderline items are re-verified when their batch runs.

### Uncovered-service classification (summary)

- CPU-testable (~80): most frontends/utilities/proxies — e.g. anythingllm, hollama, lobechat, sillytavern, mikupad, aider, bifrost, optillm, pipelines, mcpo, metamcp, supergateway, mock-openai, dify, langfuse, n8n, flowise, cognee, kotaemon, opennotebook, khoj, perplexica, perplexideez, ldr, presenton, sqlchat, oterm, parllama, docling, tts, stt (`-cpu` tag), libretranslate, qdrant, drawio, dbhub, netdata, traefik, landing, k6, mistralrs (`:cpu` image), llamaswap (`:cpu`), localai (CPU version), ikllamacpp (`IMAGE_CPU`), litlytics, mindsdb, mcpforge, nanobot, needle, npcsh, mi, agent, gum, facts, hf, hfdownloader, harbor-cli, repopack, qrgen, tokscale, openhands, opint, openterminal, openfang, sim, karakeep, activepieces, windmill, onyx, bionicgpt, surfsense, airweave, postiz, daytona, photoprism, homeassistant, browseruse, chatnio, agentzero, astrbot, beszel, bolt, deerflow, latentscope, ml-intern, bench, lmeval, omnichain, ol1, open-design, raglite, resume-matcher, ros-mcp-server, textgrad, solo, pipelines, mikupad, sillytavern.
- GPU-ROCm-testable on this host (6 paths): llamacpp.rocm (`HARBOR_LLAMACPP_IMAGE_ROCM`, kyuz0/amd-strix-halo-toolboxes), ollama.rocm (`:rocm` tag), localai.rocm, lemonade (AMD-native, rocm overlay), vllm (rocm overlay), voicebox (rocm overlay).
- needs-external-API-key (4): openclaw (Claude session), autogpt (OpenAI), cfd (Cloudflare tunnel token), morphic (search API; `.ollama` overlay exists but search side needs keys — verify at batch time).
- impractical here (~12): NVIDIA-only inference/training — aphrodite, tgi, tabbyapi, sglang, lmdeploy, ktransformers, airllm, unsloth, unsloth-studio; Apple-Silicon-only — mlx, omlx; heavy vision downloads — omniparser.

### Depth gaps in covered services (startup/health only, no functional exercise)

- webui: no chat round trip through its API (only /health + version).
- chatui: front page only — no conversation.
- librechat: config API only — no chat.
- promptfoo: /health only — no actual eval run.
- jupyter: /api only — no kernel execution.
- langflow: version only — no flow execution.
- litellm: liveliness only; never proxied a request. No `litellm.ollama`/`litellm.llamacpp` config fragment exists (product gap candidate — only dmr/mlx/omlx/npcsh/tgi/vllm/optillm/langfuse fragments ship).
- searxng: one JSON query — no category/engine coverage.
- boost: only `autotemp` exercised; 27 other modules untested (klmbr, rcn, markov, mcts, g1, tools, workflows, …).
- comfyui: system_stats only — no workflow submission.
- txtairag: Streamlit 200 only (RAG needs bigger model — candidate for ROCm batch).
- webtop: desktop 200 only.
- kobold/speaches: already functional (generate / TTS→STT) — no gap.

### Integration (compose.x) gaps among covered services

500 `compose.x.*` overlays exist; ~0 were explicitly exercised. Testable now with covered services: webui×{ollama, llamacpp, searxng, boost, litellm, speaches, kobold, pipelines}, chatui×{llamacpp, ollama, searxng}, boost×{llamacpp, ollama, litellm}, promptfoo×{ollama, llamacpp}, aichat×llamacpp, gptme×ollama (implicitly used), fabric×{ollama, litellm}, cmdh×{ollama, harbor}, plandex×{ollama, llamacpp, litellm}, langflow×litellm, txtairag×ollama, khoj×searxng, litellm×{optillm, langfuse}.

### Prioritized batches (one iteration each, highest user value first)

1. Batch I — depth + integrations of already-covered services (no new pulls): webui×ollama chat round trip via webui API; webui×searxng web-search-enabled answer; webui×boost model visibility; chatui×llamacpp conversation; promptfoo real eval vs ollama; langflow flow execution (API); jupyter kernel execute; litellm actually proxying (verify fragment gap, decide fix); searxng category queries; boost 4–6 more modules (klmbr, rcn, g1, tools).
2. Batch J — ROCm on Strix Halo: llamacpp.rocm (kyuz0 image) inference + speed sanity, ollama.rocm generate, lemonade (AMD-native) health+completion, localai.rocm; document vllm/voicebox rocm results (may be heavy).
3. Batch K — lightweight standalone CPU web services: hollama, mikupad, sillytavern, lobechat, dbhub, drawio, libretranslate (translate round trip), qdrant (collection CRUD), netdata, traefik (routing to one covered service), landing, mock-openai.
4. Batch L — LLM frontends/agents via ollama (qwen3:0.6b): anythingllm, khoj(×searxng), perplexica(×searxng), ldr(×searxng), presenton, sqlchat, oterm, parllama, aider (one-shot), opint.
5. Batch M — proxies/gateways/MCP: bifrost (+llamacpp/ollama bootstraps), optillm×ollama, litellm×optillm, pipelines (+webui.pipelines), mcpo (mcp-server-time overlay), metamcp, supergateway, mcp-inspector.
6. Batch N — RAG/workflow stacks (heavier, CPU): dify (11 containers), langfuse (+litellm.langfuse tracing round trip), n8n, flowise, cognee×ollama, kotaemon×ollama, opennotebook×ollama.
7. Batch O — speech/vision/docs CPU: tts, stt (`-cpu`), docling conversion round trip, photoprism×ollama, latentscope, libretranslate if not done in K.
8. Batch P — heavy multi-container platforms (as time allows, startup+API smoke): onyx, bionicgpt, windmill, surfsense, airweave, sim, karakeep, activepieces, postiz, daytona, mindsdb, homeassistant.

Deferred: needs-key set (openclaw, autogpt, cfd, morphic full path) and impractical set (NVIDIA-only, Apple-only, omniparser) — document, don't test.

### Run 2026-07-20 — Group I (depth + integrations)

Runner: `./tests/services-integration.sh --groups I` — final run: 22 passed,
0 failed, 0 skipped.

```
CHECK: I1 webui chat round trip
COMMAND: signup + role promote in webui.db, then POST /api/chat/completions (model unsloth/Qwen3.5-0.8B-GGUF:Q4_K_M)
EXPECTED: non-empty .choices[0].message.content
ACTUAL: non-empty reply; test user removed afterwards
RESULT: PASS

CHECK: I2 searxng categories images / it
COMMAND: GET /search?q=github&categories=<cat>&format=json
EXPECTED: .results is an array
ACTUAL: arrays for both categories
RESULT: PASS (x2)

CHECK: I3 litellm proxying (new llamacpp overlay)
COMMAND: GET /v1/models; POST /v1/chat/completions model=llamacpp/unsloth/Qwen3.5-0.8B-GGUF:Q4_K_M
EXPECTED: models non-empty; non-empty content
ACTUAL: wildcard entry served; completion proxied to llama.cpp router
RESULT: PASS (x2) — closes the "litellm never proxied" gap via services/litellm/litellm.llamacpp.yaml + compose.x.litellm.llamacpp.yml

CHECK: I4 boost modules klmbr rcn g1 mcts eli5 concept ponder
COMMAND: POST /v1/chat/completions per <module>-<model>, max_tokens 2000, -m 900
EXPECTED: non-empty content each
ACTUAL: all 7 PASS. First run: rcn/g1 FAILED — two real findings:
  (1) product defect (fact cvg): g1 appends consecutive assistant messages;
      llama.cpp 400s "Cannot have 2 or more assistant messages at the end of
      the list". Fixed: ChatNode.history() merges consecutive same-role plain
      messages (tool messages exempt); boost pytest suite green (2403 passed).
  (2) bad expectation: rcn/g1 capture intermediate completion *content*;
      thinking models emit only reasoning_content there → empty turns and
      final answers. Spec/runner now use LFM2.5 (non-thinking) for rcn/g1.
RESULT: PASS (x7)

CHECK: I5 jupyter kernel execute
COMMAND: docker exec harbor.jupyter python -c '<jupyter_client: execute print(6*7)>'
EXPECTED: 42 on iopub stream
ACTUAL: 42
RESULT: PASS

CHECK: I6 promptfoo eval run
COMMAND: promptfoo eval -c pf.yaml (provider ollama:chat:qwen3:0.6b, javascript output.length>0 assert)
EXPECTED: exit 0
ACTUAL: exit 0 — eval executed against ollama, assertion passed
RESULT: PASS

CHECK: I7 comfyui workflow (CPU)
COMMAND: POST /prompt EmptyImage→SaveImage; poll /history/<id>
EXPECTED: outputs present
ACTUAL: prompt_id 402770d7…, outputs within 120 s
RESULT: PASS

Deferred to a later batch: chatui/librechat chat round trips (session/auth
bootstrap), langflow flow execution (needs flow import).

### Run 2026-07-20 — Group I (full re-run incl. new I8–I10)

`./tests/services-integration.sh --groups I` after adding sub-batch I-d.

CHECK: I0–I7 (previously established depth checks)
ACTUAL: all PASS — webui chat, searxng categories (images/it), litellm proxy
(models + llamacpp/$MODEL completion), boost modules klmbr/rcn/g1/mcts/eli5/
concept/ponder, jupyter kernel 6*7→42, promptfoo eval rc=0, comfyui workflow
prompt_id e403cce4
RESULT: PASS (22 checks)

CHECK: I8 chatui chat round trip
COMMAND: POST /conversation (model) → POST /conversation/<id> multipart data
with rootMessageId + Origin header → GET /api/v2/conversations/<id> assistant
content non-empty
EXPECTED: non-empty assistant reply
ACTUAL: first scripted run FAIL with $MODEL (Qwen3.5-0.8B): chatui sends no
max_tokens and the thinking model decoded 74k+ tokens without stopping (the
message POST never returns). Bad expectation — switched I8 to the
non-thinking LFM2.5 model; re-verified: stream reaches
{"status":"finished"}, assistant content ends with "PONG"
RESULT: PASS (after model fix). Product defect found and fixed on the way in
(fact zfx): chat-ui >= 0.10 ignores the MODELS env — Harbor's config was
silently dropped and chatui served HuggingFace's default catalog;
envify.js now bridges the first configured endpoint to
OPENAI_BASE_URL/OPENAI_API_KEY, after which chatui lists the llamacpp
router models

CHECK: I9 librechat chat round trip
COMMAND: create-user script → /api/auth/login → GET /api/models →
POST /api/agents/chat/ollama (browser UA, endpoint "ollama",
endpointType "custom", model qwen3:0.6b) → poll /api/messages/<cid>
EXPECTED: non-user message with text
ACTUAL: PASS — assistant reply present (content[] type "text"); test user
deleted via mongosh afterwards
RESULT: PASS. Product defect found and fixed (fact 4kv): librechat.yml set
the Ollama baseURL to .../v1/chat/completions; LibreChat's client appends
/chat/completions itself → 404 MODEL_NOT_FOUND on every chat. Fixed to
.../v1. Also documented: uaParser rejects non-browser UAs ("Illegal
request"), endpoint name must be lowercase "ollama" ("Unknown endpoint"
otherwise), /api/models must be fetched first (endpoint_models_not_loaded)

CHECK: I10 langflow flow execution
COMMAND: tests/lib/langflow-flow.py — auto_login token → build ChatInput→
ChatOutput passthrough from live /api/v1/all catalog → POST /api/v1/flows/ →
mint API key → POST /api/v1/run/<id> input "PONG-services-it" → delete flow
EXPECTED: output text echoes input exactly
ACTUAL: PASS — output "PONG-services-it"; run API 403s on JWT alone
(x-api-key required), some endpoints gzip regardless of Accept-Encoding
RESULT: PASS

Summary: 29 passed, 1 failed on first scripted run; sole FAIL (I8) was a bad
model expectation, fixed in runner+spec and re-verified green. Two real
product defects fixed (chatui envify OPENAI_* bridge — fact zfx; librechat
Ollama baseURL — fact 4kv). Teardown: harbor down, test users removed, no
config drift (I-d sets no config).

### Run 2026-07-20 — Group J (ROCm paths, AMD Strix Halo / gfx1151)

Runner: `./tests/services-integration.sh --groups J` → 17 passed, 0 failed,
1 skipped (J6, by design — see below).

CHECK: J1 llamacpp.rocm
COMMAND: harbor up llamacpp; docker inspect + docker logs + chat completion
EXPECTED: rocm overlay image + /dev/kfd,/dev/dri; ROCm0 device line; inference
ACTUAL: image kyuz0/amd-strix-halo-toolboxes:rocm-7.2.4 (host override of
  llamacpp.image_rocm), devices passed; `ROCm0 : AMD Radeon 8060S Graphics
  (122880 MiB)`; Qwen3.5-0.8B completion ~4 s (156 tok/s eval observed)
RESULT: PASS

CHECK: J2 ollama.rocm
COMMAND: harbor up ollama; logs; pull qwen3:0.6b; /api/generate; ollama ps
EXPECTED: ollama/ollama:rocm, library=ROCm, generation on GPU
ACTUAL: `inference compute … library=ROCm compute=gfx1151 name=ROCm0
  description="Radeon 8060S Graphics"`; generate ok; `ollama ps` 100% GPU;
  228 tok/s eval
RESULT: PASS

CHECK: J3 lemonade (rocm overlay)
COMMAND: harbor up lemonade; env check; register cached GGUF; chat
EXPECTED: LEMONADE_LLAMACPP=rocm, rocm backend used, inference
ACTUAL: env set by overlay; system-info: rocm backend `installed`, device
  amd_gpu; `Using LlamaCpp Backend: rocm-preview`, `loaded ROCm backend
  (libggml-hip.so)`, ROCm0 model/KV buffers; completion ok
RESULT: PASS

CHECK: J4 localai.rocm
COMMAND: harbor up localai; gallery install qwen3-0.6b; chat
EXPECTED: latest-gpu-hipblas image, GPU inference
ACTUAL: image localai/localai:latest-gpu-hipblas (4.3 GB pull), devices
  passed; auto-installed `rocm-hipblas-llama-cpp` OCI backend (3.1 GB,
  GPU-detected selection), n_gpu_layers=99999999; completion ~3.5 s;
  rocm-smi showed 14% GPU use mid-generation
RESULT: PASS

CHECK: J5 voicebox (rocm overlay)
COMMAND: harbor up voicebox; docker inspect; /health
EXPECTED: devices + video group passed, health 200
ACTUAL: /dev/kfd,/dev/dri + group video present, health 200 — but
  `"gpu_available": false, "backend_variant": "cpu"`; torch.version.hip=None
  (upstream Dockerfile installs CPU torch). Startup+devices PASS; GPU use is
  an upstream image limitation, documented in the spec (not fixed here)
RESULT: PASS (limitation documented)

CHECK: J6 vllm.rocm
COMMAND: runner SKIPs on default CUDA image; manual procedure verified
EXPECTED: SKIP by default; documented ROCm procedure works
ACTUAL: SKIP recorded. Manually verified 2026-07-20: vllm.image
  kyuz0/vllm-therock-gfx1151:stable + Qwen/Qwen3-0.6B +
  `--max-model-len 4096 --gpu-memory-utilization 0.35` → health 200 in
  ~140 s, ROCm attention backend (`ROCM_ATTN`) selected, completion in
  ~4.8 s. All five vllm config keys restored afterwards
RESULT: SKIP (default) / PASS (manual)

Triage notes from stabilizing this group (all runner bugs, no product
defects):
- `grep -q` on `docker logs |` pipelines under `set -o pipefail` SIGPIPEs
  docker logs on match → pipeline reports failure on success. Fixed by using
  full-read `grep >/dev/null`.
- llamacpp ROCm0 device line only appears once a model loads — the grep must
  run after the inference, not at startup.
- lemonade `POST /api/v1/delete` deletes checkpoint files from the SHARED HF
  cache (removed Qwen3.5-0.8B Q4_K_M used by other groups; re-downloaded to
  restore). The runner no longer deletes its registered model.
- Q4_K_M Qwen3.5-0.8B deterministically spends the whole budget on
  reasoning_content; GPU inference checks accept content OR
  reasoning_content.

### Run 2026-07-20 — Group K (lightweight standalone CPU web services)

Runner: `./tests/services-integration.sh --groups K` — final run: 19 passed,
0 failed, 0 skipped.

```
CHECK: K1 landing
COMMAND: GET / + GET /docs/
EXPECTED: 200; index contains 'harbor'; /docs autoindex lists entries
ACTUAL: 200 after 0s; both content checks matched
RESULT: PASS (x3)

CHECK: K2 hollama
COMMAND: GET /
EXPECTED: 200 + SPA index contains 'hollama'
ACTUAL: 200 after 0s; matched
RESULT: PASS (x2)

CHECK: K3 mikupad
COMMAND: GET / (image built from github.com/lmg-anon/mikupad#main)
EXPECTED: 200 + body contains 'mikupad'
ACTUAL: 200 after 0s; matched
RESULT: PASS (x2)

CHECK: K4 mock-openai
COMMAND: GET /v1/models; POST /v1/chat/completions
EXPECTED: .data[0].id == "mock-model"; non-empty .choices[0].message.content
ACTUAL: mock-model; "Hello from mock-openai!"
RESULT: PASS (x3)

CHECK: K5 qdrant
COMMAND: PUT collection (size 4, Dot) + upsert 2 points + search [0.9,0.1,0.1,0.1] + delete (api-key auth)
EXPECTED: .result == true; top search hit id == 2
ACTUAL: created; top hit id=2; collection deleted
RESULT: PASS (x3)

CHECK: K6 libretranslate
COMMAND: LT_LOAD_ONLY=en,es; GET /languages; POST /translate en->es "hello world"
EXPECTED: 200; .translatedText non-empty and != input
ACTUAL: "hola mundo"
RESULT: PASS (x2) — after product fix (run-as-host-user + XDG pinning, fact plx)

CHECK: K7 netdata
COMMAND: GET /api/v1/info
EXPECTED: 200 + non-empty .version
ACTUAL: v2.10.4
RESULT: PASS (x2)

CHECK: K8 dbhub
COMMAND: POST /mcp initialize; tools/call execute_sql "SELECT 6*7 AS answer"
EXPECTED: serverInfo.name non-empty; rows [{"answer":42}]
ACTUAL: "DBHub MCP Server"; 42
RESULT: PASS (x2) — initial /message+SSE expectation was wrong (endpoint is /mcp, plain JSON, stateless); spec fixed

Product defect (libretranslate, fact plx @implemented): first boot crash-looped —
PermissionError on /home/libretranslate/.local/share then .config, plus
"Error: '' is not a valid port number" fallout. Root cause: init sidecar chowns
the workspace mounts to the host user, but the upstream image runs as uid 1032
(libretranslate:nogroup), which then cannot write its own mounts. Fix in
compose.libretranslate.yml: run as ${HARBOR_USER_ID}:${HARBOR_GROUP_ID} with
HOME=/home/libretranslate and XDG_DATA/CACHE/CONFIG_HOME pinned inside the
mounted .local (the image-owned home dir itself is not writable).

Dev-tooling defect (fact x56 @implemented): `harbor dev lint --strict` crashed
(WalkError) on root-owned services/netdata/cache after running netdata — the
bash pass's global-exclude expandGlob had no runtime-dir excludes. Fix:
RUNTIME_DIR_EXCLUDES shared from .scripts/lint/util.ts, netdata cache/lib added.

Runner pitfall (recurring): `grep -q` on a curl pipe under pipefail SIGPIPEs
curl on early match -> flaky FAIL (hit on K3). Same class as the docker-logs
case from Group J; all Group K content checks use full-read `grep -i ... >/dev/null`.
```
