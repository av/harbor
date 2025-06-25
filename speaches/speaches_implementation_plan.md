# Harbor speaches Native Integration


Your Process:
continue to think step by step "out loud" and justify your reasoning throughout the following, write the areas of expertise needed then act as an expert in those areas, for each area of expertise write 10 best practices generally and 10 best practices specifically for the following, critique your work overall and line by line and propose multiple solutions to each and choose the best solution this needs to make a compelling case, also describe the logic flow as you go through the description. Make sure to use actual quotes whenever possible. Requirement: After every step and sub-step of your plan both as you create it and as you execute it you must say "Wait," and do your wait process "out loud". Each thread of updates needs to be assigned a unique name, with an incrementing version number (<taskname>-v1, <taskname>-v2, …). Check your work. Do not hallucinate.


You must do your wait process too: Your wait process: After every step and sub-step of your plan both as you create it and as you execute it you must say "Wait," and check "out loud" if there is an issue or something you need to consider and you must make short lists of new general and specific best practices then harshly and constructively critique your work overall and line by line against every single best practice and criteria as well as a pre-mortem and propose multiple concrete solutions both at a high level and as proposed quotes to each and and then use the critiques to make a third proposed quote then choose the best solution from all of the above including the original and the final solution must be a compelling case, and if the wait process caught an error you must immediately insert and execute new steps to your task in which you redo the original work correctly. The goal of your wait process is to work towards your overall goal and be sufficiently detailed and verifiable that the outcomes can be verified by others in place, therefore direct quotes and meaningful justifications that show why the assessment is made and not just tell what the assessment is are absolutely essential.

Your Task:

the goal is to launch speaches_service_manager.py as one process as a harbor native process and have it work by default as compose.speaches.yml does with the addition of gpu support on macos.

---

## ✅ **COMPLETED**

- [x] **Outlined best practices** for hybrid orchestration, native service config, Docker Compose, Bash scripting, GPU/Apple Silicon support, and ONNX Runtime.
- [x] **Located and reviewed** current speaches service implementation in Harbor (harbor.sh, env files, Docker Compose, WebUI config).
- [x] **Designed and iteratively updated** a native execution contract for speaches:
  - [x] Created and updated speaches_native.yml and speaches_native.sh (with ONNX provider detection, robust install logic, uv/pip fallback, and improved error handling).
  - [x] Made the bootstrap script executable.
- [x] **Implemented robust ONNX provider detection and setup** in onnx_utils.py.
- [x] **Created service_manager.py (now speaches_service_manager.py)** to manage ONNX/kokoro/hf_utils lifecycle and environment setup as part of the speaches service.
- [x] **Updated speaches_native.sh** to:
  - [x] Prefer uv-managed environments for execution.
  - [x] Integrate ONNX provider setup via both Bash and Python utility.
  - [x] Use the new service manager for enhanced initialization.
  - [x] Make the executable parameter optional, defaulting to launching the service manager.
- [x] **Updated pyproject.toml**:
  - [x] Uses git+https for speaches and `kokoro-onnx` for uv compatibility.
  - [x] Added `[project.scripts]` entries for `harbor-speaches`, `harbor-speaches-server`, and `harbor-speaches-test`.
- [x] **Removed CLI/test code** from `hf_utils.py` and `kokoro_utils.py`, created speaches_test.py for all test/CLI functionality.
- [x] **Created config_defaults.yml** with best-practices configuration.
- [x] **Restored missing GPU/provider utility functions** (`setup_kokoro_providers`, `create_gpu_kokoro`, `test_kokoro_gpu_acceleration`) to kokoro_utils.py to match service manager imports.
- [x] **Confirmed that the test suite** in speaches_test.py uses the correct utility functions.
- [x] **Diagnosed and explained the Python version conflict**: `speaches[server]` requires Python >=3.12,<3.13, but the rest of the stack (notably `llvmlite` via `librosa/numba`) requires Python <=3.10.
- [x] **Provided and implemented a robust patching function** in `speaches_native.sh` to update pyproject.toml's `requires-python` to allow Python 3.10, using relative paths and a version-agnostic sed command, with a commented-out commit step.
- [x] **Updated `speaches_native.sh` to expose a CLI utility** (`--patch-speaches-pyproject`) for patching the local repo.
- [x] **Updated `install_with_uv` in `speaches_native.sh`** to:
  - [x] First try `uv pip install speaches[server]`.
  - [x] If that fails, clone the repo, patch pyproject.toml for Python 3.10, and install from the local repo.
- [x] **Added `try_uv_pip_install` and updated `install_with_uv`** in `speaches_native.sh`.

---

## 🟡 **CURRENT STATUS**

- [x] All core scripts, configs, and test scaffolding are in place.
- [x] Native install/launch logic is robust and cross-platform, with fallback and patching for Python 3.10.
- [x] Service manager and ONNX provider detection are integrated.
- [x] Test suite exists and covers basic functionality.
- [ ] Some edge cases, error handling, and full integration tests remain to be completed.

---

## ⬜️ **PENDING / TO DO**

### 1. **Finalize and Harden Native Installation/Execution**

- [ ] Rename config_default.yml and update speaches_service_manager.py to have its parameter loading be compatible with speaches_native.yml (speaches_native.yml is based on ollama_native.yml)
- [ ] update speaches_native.yml to use the models provided by default in hf_utils.py and kokoro_utils.py
- [ ] Test the fallback logic in `speaches_native.sh` for all supported platforms (macOS/Apple Silicon, Linux/NVIDIA, CPU-only).
- [ ] Check then test the automated patching logic for pyproject.toml to ensure Python 3.10 compatibility is reliably applied.
- [ ] Verify that both uv install path results in a working, importable speaches package and working CLI entrypoints.

### 2. **Expand and Harden `speaches_service_manager.py`**

- [ ] Add/expand tests in `speaches_test.py` to cover:
  - [ ] Configuration priority hierarchy: CLI > env > YAML > defaults.
  - [ ] Argument parsing and propagation to TTS/STT/voice submodules.
  - [ ] ONNX provider detection and fallback logic.
  - [ ] Lifecycle management for both TTS and STT (ensure both are started/stopped as expected).
  - [ ] Error handling for missing/invalid config, ports, or provider settings.
  - [ ] Logging and status output for all major actions.
- [ ] Bugfixes:
  - [ ] Ensure all subprocesses (TTS, STT, voice) lifecycles are properly started, monitored, and terminated.
  - [ ] Fix any issues with port assignment, especially when running multiple services or in parallel.
  - [ ] Harden the config loading logic to handle missing or malformed YAML, env, or CLI args.
  - [ ] Ensure ONNX provider selection is robust and falls back gracefully (e.g., MPS → CPU on Apple Silicon).
  - [ ] Add clear error messages and exit codes for all failure modes.

### 3. **Integration with Harbor and Compose**

- [ ] Review and update `speaches_native.yml` and compose.speaches.yml to ensure:
  - [ ] All ports, volumes, and environment variables are correctly mapped.
  - [ ] The service manager is the default entrypoint for native execution.
  - [ ] ONNX provider and platform-specific settings are passed through as needed.
- [ ] Update config.speaches.json and any other integration points to ensure seamless WebUI integration.
- [ ] Document the expected config flow and how to override settings for advanced users.

### 4. **Full Integration Test: `harbor up -n ollama speaches webui`**

- [ ] Test native launch of all three services together:
  - [ ] Run: `harbor up -n ollama speaches webui`
  - [ ] Verify:
    - [ ] All three services start and remain healthy.
    - [ ] Ports are correctly assigned and accessible.
    - [ ] WebUI can connect to both ollama and speaches (test TTS/STT in the UI).
    - [ ] ONNX provider is correctly detected and used (check logs for provider selection).
    - [ ] No conflicts or race conditions in port or resource allocation.
- [ ] Test fallback scenarios:
  - [ ] verify CPU fallback without gpu works.
  - [ ] On Apple Silicon, verify MPS/CoreML fallback and then CPU fallback.
  - [ ] Simulate partial failures (e.g., missing dependency) and verify error handling.
- [ ] Test containerized fallback:
  - [ ] Run: `harbor up speaches` (without `-n`) and verify container path still works.

### 5. **Documentation and Troubleshooting**

- [ ] Update documentation:
  - [ ] Native install and launch instructions.
  - [ ] How to patch for Python 3.10.
  - [ ] How to override ONNX provider or ports.
  - [ ] How to debug and report issues.
- [ ] Add troubleshooting section for:
  - [ ] Python/uv/pip issues.
  - [ ] ONNX provider errors.
  - [ ] Harbor orchestration issues.
  - [ ] WebUI integration problems.


# **Pre-mortem and Iterative Improvement To Be Done As-Needed Throughout the Process**

- [ ] Review logs and user experience from all tests.
- [ ] Identify and fix any remaining rough edges, race conditions, or confusing error messages.
- [ ] Iterate on the service manager and native script as needed while keeping to the intended scope.
- [ ] Running requests and tool calls is expensive so bundle them together whenever possible to do a whole task at once, e.g. make or update a test file with many tests and run it, or run a full sequence of commands in one terminal line, or other ideas that make your task get done in fewer steps.
- [ ] When working with this as an AI, periodically refer back to and update this speaches_implementation_plan.md as progress proceeds at good stopping points.
- [ ] At good stopping points update the current progress in this speaches_implementation_plan.md file and double check your next steps to see if it can be simplified or if steps were missed, then prepare a commit and ask the user before making it.
- [ ] Stay focused on task and see how you can meet the goals effectively as intended in fewer steps.

---

**Legend:**
- ✅ = Completed
- 🟡 = Current status
- ⬜️ = Pending/To do




# Harbor Executive Summary

**Objective**: To enable Harbor to seamlessly run AI services natively on the host machine while maintaining full network integration with other containerized services. This is achieved by enhancing Harbor's Deno-based composition engine to support a "surgical exclusion" pattern for Docker Compose files.

**Core Implementation**: The `harbor up -x <service>` command will trigger an enhanced Deno routine that intelligently excludes the container definition for the specified service (e.g., `compose.ollama.yml`) but includes its native proxy contract (`ollama/ollama_native.yml`). This ensures the native process runs on the host while a lightweight proxy container bridges it to the Docker network, preserving all cross-service dependencies.

**Result**: A user can run `harbor up -n speaches ollama webui` to launch Ollama and speaches natively for maximum performance and direct GPU access, while the `webui` service runs in a container and can still communicate with Ollama as if it were another container.

## Harbor Project Overview

### What is Harbor?
Do not confuse this project with the Harbor container registry. This is a different project with the same name.

Harbor is a containerized LLM toolkit that allows you to run LLMs and additional services. It consists of a CLI and a companion App that allows you to manage and run AI services with ease. Harbor is in essence a very large Docker Compose project with extra conventions and tools for managing it.

### Harbor's Core Design Principles

1.  **Unified Service Management** - A single CLI for both container and native service execution.
2.  **Dynamic Composition** - Services are composed from multiple YAML files based on context.
3.  **Hybrid Runtime Support** - Services can run natively (on the host) or in containers simultaneously.
4.  **Service Discovery** - All services can communicate regardless of their runtime mode.
5.  **Performance Optimization** - Native execution is a first-class citizen for performance-critical services.

### Components
Harbor consists of:
- **CLI**: Primarily written in Bash, see [harbor.sh](../harbor.sh) (a VERY large file). The CLI is in transition to using TypeScript with Deno for performance-critical sections; you'll see this concept as "routines."
- **Desktop App**: Written with Tauri, React, and DaisyUI, located in the `/app` directory.

### Repository Structure
- `.` - The root of the project, also referred to as `$(harbor home)`.
- `/docs` - Project and service documentation.
- `/app` - The Tauri desktop application source.
- `/routines` - Deno/TypeScript modules used by the Bash CLI.
- `/<service>` - Directories for each service, containing their `compose.*.yml` files and native contracts.
- `/speaches` - the service currently being worked on which is a text to speech and speech to text system that integrates with open webui
- `/webui` - the open webui service

### Relevant Docs
- [Adding a new service](../docs/7.-Adding-A-New-Service.md)

## The Core Task: Hybrid Orchestration

The primary goal of this task is to solve a fundamental limitation for AI developers, **especially on macOS where Docker does not support GPU passthrough.** This feature allows running performance-sensitive services like LLMs natively on the host to get direct, un-virtualized GPU access, while keeping other services (like web UIs or databases) conveniently containerized.

This is achieved through a **"Surgical Exclusion and Proxy Replacement"** pattern.

**Concrete Example: `harbor up -x ollama webui`**

1.  **User Intent**: Run `ollama` natively for performance, but run the `webui` in a container for convenience.
2.  **Harbor's Action**: The composition engine is invoked with `ollama` in an "exclusion" list.
3.  **Surgical Exclusion**: The engine resolves the list of compose files to include:
    *   `compose.yml` (base configuration)
    *   `compose.webui.yml` (WebUI container definition)
    *   `compose.x.webui.ollama.yml` (networking glue between WebUI and Ollama - **PRESERVED**).
    *   `compose.ollama.yml` (Ollama container definition - **EXCLUDED**).
4.  **Proxy Replacement**: The engine then adds the native contract file to the list:
    *   `ollama/ollama_native.yml` (contains the lightweight `socat` proxy container definition - **INCLUDED**).
5.  **Final State**: Harbor runs `docker compose up` on a merged file containing the `webui` container and the `ollama` proxy container. Simultaneously, it starts the `ollama serve` process natively on the host. The `webui` container communicates with the `ollama` proxy, which forwards traffic to the native process, achieving seamless integration.


### File Naming Conventions: The Core of the Logic

The entire hybrid orchestration system relies on a strict and meaningful file naming convention. Understanding this is critical.

*   `compose.<service>.yml`: **Container Definition**. This file defines how to run `<service>` in a container. It **MUST be excluded** when running natively.
    *   *Rationale*: Including this file would launch the container, creating a conflict with the native process and defeating the purpose of hybrid execution.
*   `compose.x.<svc1>.<svc2>.yml`: **Integration File**. This file defines how services connect (e.g., environment variables, network aliases). It **MUST be preserved** regardless of their runtime mode.
    *   *Rationale*: The integration logic is essential for services to communicate, whether they are native or containerized. The `webui` container still needs to know how to find `ollama`.
*   `<service>/<service>_native.yml`: **Native Contract & Proxy**. This dual-purpose file is the key to the solution. It contains the lightweight proxy container definition (visible to Docker Compose) and the native process metadata in an `x-harbor-native` block (used by Harbor's scripts).
    *   *Rationale*: This file is **included as a replacement** for the excluded container definition, bridging the native process into the Docker ecosystem.
*   `compose.<service>.<capability>.yml`: **Capability File**. Adds functionality like GPU support or other hardware acceleration (e.g., `compose.ollama.nvidia.yml`, `compose.rocm.yml`). These are preserved as they are relevant to both runtimes.


### What to Avoid
1.  **Don't modify core Harbor patterns** like the service naming conventions.
2.  **Don't break Docker Compose compatibility**
3.  **Don't add heavy dependencies**
4.  **Don't duplicate logic**
5.  **Don't break backwards compatibility**


### The Iterative Design Process
When faced with a complex problem, check sepaches_implementation_plan.md and follow this structured thinking process:
1.  **High-Level Plan**: State the goal and break it into phases.
2.  **Concrete Options**: Propose 3-5 distinct, concrete implementation options. Use code snippets. Consider DRY principles and the principle of least surpirse.
3.  **Harsh and Constructive Critique**: Constructively critique each option against best practices (general and task-specific). Identify flaws, risks, tradeoffs, and regressions. Do a pre-mortem and propose clean well-designed and minimal solutions that meet best practices and reduce complexity while effectively meeting the goal.
4.  **Cross-Pollinate & Synthesize**: Create 1-3 new, higher-quality solutions by combining the best aspects of the initial options and addressing their critiques.
5.  **Decision**: Choose the best synthesized solution and justify why it's optimal in terms of risk, maintainability, scope, and meeting requirements.
6. **Bookkeeping**: Keep track of your task progress by writing to this speaches_implementation_plan.md file the what, why, and how of steps you have:
   1.  completed,
   2.  are currently working on,
   3.  expect to do next,
   4.  what changes have been made to the original plan and why, and
   5.  critique your edits periodically to ensure they are in line with best practices and your goals.
   6.  periodically update this document.