---
name: test-boost-module
description: >
  Live-test a Harbor Boost module by sending a real prompt through llamacpp via pi
  and validating the output. Use when asked to test a boost module, verify a module
  works, check module behavior, QA a boost module, or confirm a module's effect on
  LLM output.
---

# Test Boost Module

Send a real prompt through a running Boost module via `harbor launch` + `pi` and
validate the output yourself. This is a live integration test, not a unit test.

## Prerequisites

- `llamacpp` running (`harbor up llamacpp`)
- `boost` running (`harbor up boost`)
- `pi` installed on the host

If services aren't running, start them. Wait for health checks before proceeding.

## Picking a Test Model

Use a small-to-mid model already available in llamacpp. Check what's loaded:

```bash
curl -s -H "Authorization: Bearer sk-boost" http://localhost:$(docker port harbor.boost 8000/tcp | head -1 | cut -d: -f2)/v1/models | python3 -c "
import sys, json
for m in json.load(sys.stdin).get('data', []):
    if m.get('status', {}).get('value') == 'loaded':
        print(f\"  LOADED  {m['id']}\")
    else:
        print(f\"  avail   {m['id']}\")
" 2>/dev/null
```

Good defaults (if available): `unsloth/Qwen3.6-35B-A3B-GGUF:Q4_K_XL`,
`unsloth/Qwen3.5-4B-GGUF:Q4_K_M`, or any loaded non-embedding model.
Strip the module prefix from the model ID when passing to `--model`.

## The Command

```bash
harbor launch --workflow <module_name> --model "<base_model_id>" pi \
  -p --no-tools --no-session "<prompt>"
```

- `--workflow <module_name>` routes through Boost with that module active
- `--model` is the base llamacpp model (no module prefix)
- `-p` makes pi print-and-exit (non-interactive)
- `--no-tools` disables tool use for a clean completion
- `--no-session` keeps it ephemeral

### Argument order matters

Launch options (`--workflow`, `--model`, `--backend`) go **before** `pi`.
Pi options (`-p`, `--no-tools`) and the prompt go **after** `pi`.

## Choosing the Right Prompt

The prompt should make the module's effect **obvious** in the output. Pick a prompt
that produces clearly different output with vs. without the module.

### Prompt strategies by module type

| Module type | Good prompt | What to look for |
|-------------|-------------|------------------|
| **Style/compression** (caveman, ponytail) | "Explain the theory of relativity in detail" | Terse fragments or minimal-build guidance vs. normal prose |
| **Reasoning chain** (g1, mcts, ponder) | "What is 27 * 43?" or a logic puzzle | Visible thinking steps, multi-pass reasoning |
| **Research/retrieval** (quickhop, deephop) | "What are the latest developments in fusion energy?" | Citations, search steps, retrieved context |
| **Output transform** (eli5, klmbr, rcn) | "Explain quantum entanglement" | Simplified language, restructured output |
| **Guard/check** (autocheck, diffscope) | A coding deliverable with explicit file scope | Post-answer self-check or scope warnings |
| **Prompt injection** (dnd, dot, nbs) | Any general question | System prompt artifacts, altered persona |

If you don't know the module type, read the module's `DOCS` string and `apply()`
function in `services/boost/src/modules/<name>.py` first.

## Running the Test

1. **Read the module source** to understand what it does:
   ```bash
   # Check DOCS and apply() in the module
   cat services/boost/src/modules/<name>.py
   ```

2. **Run with the module** (the test):
   ```bash
   harbor launch --workflow <module> --model "<model>" pi \
     -p --no-tools --no-session "<prompt>"
   ```

3. **Run without the module** (the control), using the same model and prompt:
   ```bash
   harbor launch --model "<model>" pi \
     -p --no-tools --no-session "<prompt>"
   ```

4. **Compare outputs.** The module's effect should be clearly visible. If the outputs
   are indistinguishable, either:
   - The prompt doesn't exercise the module's behavior — pick a better prompt
   - The module isn't activating — check Boost logs: `docker logs harbor.boost --tail 20`
   - The module has a bug

## Validation Checklist

After running both commands, answer these questions:

- [ ] **Activated?** Does the output differ from the control run in the expected way?
- [ ] **Correct?** Is the module's transformation accurate (not garbled, not hallucinated)?
- [ ] **Complete?** Does the full response arrive (no truncation, no hanging)?
- [ ] **Clean?** No error messages, no leaked internal prompts, no broken formatting?
- [ ] **Proportional?** Is the module's effect appropriate (not too aggressive, not invisible)?

Report PASS/FAIL for each item with a one-line reason.

## Troubleshooting

**"Unsupported launch workflow"** — the module isn't registered as a workflow.
Verify the module file exists under `services/boost/src/modules` or
`services/boost/src/custom_modules` and has a valid `ID_PREFIX`.

**Output looks identical to control** — check that Boost reloaded the module.
Restart Boost: `harbor down boost && harbor up boost`, wait for healthy, retry.

**Timeout or hang** — pi `-p` should exit after the response. If it hangs, the
model may be too large or the prompt triggered an infinite generation loop.
Add `--timeout 30000` or kill and retry with a smaller model.

**Empty output** — the module may be swallowing the completion. Check
`docker logs harbor.boost --tail 30` for errors.
