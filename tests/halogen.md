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

Expect port 34950 mapped to 8731, upstream image 0.6.2, command `all`, GPU devices, host IPC, unlimited memlock, persistent `/models`, no restart policy, and an API healthcheck. Expect WebUI to wait for healthy Halogen and mount a config with `http://halogen:8731/v1`. Every service default must be documented and the catalog wiki link must match the doc.

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
