# Halogen integration tests

## Prerequisites

- Run from the Harbor repository with Docker Compose, Harbor, curl and jq available.
- Apply defaults with `harbor config update`.
- Runtime tests require Linux AMD Strix Halo (gfx1151), 128 GB unified memory with other large model workloads unloaded, and at least 120 GiB of disk for weights plus the image.
- Pull with `harbor pull --no-defaults halogen`. First startup downloads about 118 GiB.
- Do not stop unrelated workloads to satisfy prerequisites without authorization.

## Compose and catalog

1. Run `harbor eject --no-defaults halogen` and `harbor eject --no-defaults webui halogen`.
2. Inspect resolved Halogen configuration and the mounted WebUI configuration JSON.
3. Inspect the Halogen metadata entry and documentation.

Expect port 34950 mapped to 8731, upstream image 0.6.3, command `all`, GPU devices, host IPC, unlimited memlock, persistent `/models`, no restart policy, pool 262144, prefill 16384, host reserve 20, 4 KV slots, chat token default 65536, engine watchdog 900 seconds, and an API healthcheck. Expect WebUI to wait for healthy Halogen and mount a config with `http://halogen:8731/v1`. Every service default must be documented and the catalog wiki link must match the doc.

## Real inference

1. Run `harbor up --no-defaults halogen` and wait for healthy state, inspecting finite container logs for download/load progress.
2. GET `http://localhost:34950/v1/models` and read a returned model ID.
3. POST `/v1/chat/completions` using that ID, a user message asking `What is 2 + 2? Answer briefly.`, temperature 0 and max_tokens 256.
4. Repeat with `stream: true`.
5. Inspect container logs after both requests.

Expect a nonempty model list, HTTP 200 with assistant output containing the correct answer, SSE chunks ending in `[DONE]` for streaming, and no engine crash. A healthy container alone does not pass this test.

## Open WebUI

1. Start a disposable Open WebUI instance with the Halogen cross-file, without replacing an existing user instance.
2. Open its UI, complete onboarding if needed, select the Halogen model, and submit the same arithmetic prompt.
3. Verify the assistant answer contains 4 and the Halogen logs show the request.

Expect a successful response through Halogen. Capture `docs/harbor-halogen.png` from this workflow if a UI example is added to the documentation.

## Continuous serving

1. Start Halogen with the default Open WebUI and llamacpp stack still running.
2. POST three sequential streamed `/v1/chat/completions` requests. Each request includes a system prompt of about 6000 tokens and accumulating chat history.
3. After every turn, GET `/health` and inspect the Halogen container state. Also confirm `harbor.llamacpp` is still healthy.

Expect HTTP 200 with assistant content on every turn. The engine watchdog stays on at 900 seconds and must not stop the container. `/health` must stay successful. `harbor.llamacpp` must stay healthy. A compose restart policy is not the pass condition.

## Cleanup

Stop and remove only containers created for this test. Preserve downloaded models and all pre-existing workloads.

## Verification record (2026-09-13)

- PASS: image `ghcr.io/peonist-ai/halogen-flash-server:0.6.2` pulled successfully.
- PASS: standalone and WebUI Compose resolve and validate. Assertions confirm image, command, API mapping, IPC, memlock, no restart policy, health dependency and WebUI config mount.
- PASS: a disposable container created from the real Halogen Compose configuration can read/write the GPU device, write `/models`, find the executable healthcheck, and sees the expected API port, context and unlimited memlock. It was removed automatically.
- PASS: WebUI configuration points at `http://halogen:8731/v1`; every service default is documented.
- PASS: Compose lint, strict rules (zero findings), lint self-tests and `git diff --check`. Full lint reports only two existing SC3001 warnings in `services/tei/check-cache-init.sh`.
- Fixed during verification: the upstream Docker recommendation adds a named `render` group, but image 0.6.2 lacks that group. Reproduced Docker's startup rejection and omitted supplementary groups, matching Harbor's existing root-run AMD backend pattern. Device access passes.
- Fact `aom` PASS: resolved workspace mounts `/models` and all specified configuration values propagate into the container.
- Fact `dmo` PASS: catalog URL matches this service's doc, which covers hardware, download size, every default and a chat request.
- Fact `33b` PENDING: deployment settings pass, but real API inference is not verified.
- Fact `jfu` PENDING: cross-file and configuration pass, but the browser-to-engine workflow is not verified.
- Runtime blocker: this host has about 49 GiB available memory, with 49 GiB consumed by `/tmp` including 30 GiB in an unrelated harness workspace. No unrelated workloads or files were removed. Model download, inference, streaming and browser validation remain pending. Release must wait for these checks.

## Verification record (2026-09-16)

- PASS: the earlier `/tmp` disk blocker is gone. About 164 GiB was free before the download. The 118 GiB bundle landed in `services/halogen/models` (127 GiB on disk including sidecars).
- PASS: first start downloaded `peonist-ai/halogen-qwen3.8-flash-next` into `/models`. Checkpoint `qwen38-flash-next-w4b.hgn` is 116 GiB. A Hugging Face token was supplied at runtime so the transfer was authenticated. Existing `harbor.webui` and `harbor.llamacpp` were left running.
- PASS: GET `http://localhost:34950/v1/models` returned HTTP 200 with model id `halogen-qwen3.8-flash-next`.
- PASS: POST `/v1/chat/completions` with that id, `What is 2 + 2? Answer briefly.`, `temperature` 0 and `max_tokens` 256 returned HTTP 200. Assistant `content` was `4`.
- PASS: the same request with `stream: true` returned SSE `data:` chunks, assistant content `4`, and a final `data: [DONE]` line. The container stayed healthy. Logs show both POSTs as 200 with no engine crash (about 33 then 43 tok/s).
- PASS: a disposable Open WebUI on port 34999 joined `harbor_harbor-network`, mounted `config.halogen.json`, and did not replace `harbor.webui` on 33801. After signup it listed `halogen-qwen3.8-flash-next`. POST `/api/chat/completions` returned HTTP 200 with content `4`. Halogen logs show the matching POST from the disposable WebUI address `172.18.0.5`. No browser tool was available, so the UI was verified through that instance's HTTP API rather than a screenshot. `docs/harbor-halogen.png` was not added.
- Fact `33b` PASS: the OpenAI API answered on host port 34950 using the Strix Halo GPU.
- Fact `jfu` PASS: the WebUI halogen config reached the engine after it was healthy.
- Note: default `HALOGEN_KV_SLOTS=4` and `HALOGEN_KV_POOL_POSITIONS=524288` did not finish startup on this host. The engine lowered the pool to 262144, then spent more than 20 minutes on extra slot reservation with compaction stalls and only a few contiguous 2 MiB blocks. Inference used `HALOGEN_KV_SLOTS=1`, `HALOGEN_CTX=32768`, `HALOGEN_KV_POOL_POSITIONS=32768`, and `HALOGEN_MAX_TOK=4096`. Those overrides were not written into Harbor defaults.
- Note: the quality sidecar on disk still predates image 0.6.0 (draft head at 4 bits). Answers were unaffected.
- Cleanup: removed `harbor.halogen` and the disposable WebUI. Preserved `services/halogen/models` and the pre-existing `harbor.webui` / `harbor.llamacpp` workloads.

## Verification record (2026-09-16, continuous serving)

- PASS: defaults are image 0.6.3, `HARBOR_HALOGEN_KV_POOL_POSITIONS=262144`, `HARBOR_HALOGEN_MAX_TOK=16384`, `HARBOR_HALOGEN_HOST_RESERVE_GIB=20`. Compose passes those values. There is no restart policy.
- PASS: with `harbor.llamacpp` healthy, Halogen 0.6.3 became healthy in 34s. Startup reserved a 262144-position pool, 4 slots, 16384-token admit chunk, and left 19.9 GiB for the lookup-table file cache. The engine watchdog stayed on at 180s.
- PASS: three streamed turns with a 4103-token system prompt returned HTTP 200 with assistant content `4`, `6`, then `A, B, C`. Each turn logged an `mtp` line. `/health` stayed 200. The container did not exit.
- PASS: a later 6583-token system prompt (matching the earlier WebUI stall size) prefills in 6.5s with an `mtp` line. Five more streamed turns on that prompt, including a two-sentence decode on turn 3, all returned HTTP 200 with content. `/health` stayed 200. `harbor.llamacpp` stayed healthy. Logs have no unanswered PING.
- Fact `7sq` PASS, `w8s` PASS, `ant` PASS, `9ov` PASS.
