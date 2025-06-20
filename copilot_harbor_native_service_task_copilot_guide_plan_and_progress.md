
# Harbor Native Service Hybrid Orchestration - Technical Implementation Guide

## Executive Summary

**Objective**: To enable Harbor to seamlessly run AI services natively on the host machine while maintaining full network integration with other containerized services. This is achieved by enhancing Harbor's Deno-based composition engine to support a "surgical exclusion" pattern for Docker Compose files.

**Core Implementation**: The `harbor up -x <service>` command will trigger an enhanced Deno routine that intelligently excludes the container definition for the specified service (e.g., `compose.ollama.yml`) but includes its native proxy contract (`ollama/ollama_native.yml`). This ensures the native process runs on the host while a lightweight proxy container bridges it to the Docker network, preserving all cross-service dependencies.

**Result**: A user can run `harbor up -x ollama webui` to launch Ollama natively for maximum performance and direct GPU access, while the `webui` service runs in a container and can still communicate with Ollama as if it were another container.

## Harbor Project Overview

### What is Harbor?
Do not confuse this project with the Harbor container registry. This is a different project with the same name.

Harbor is a containerized LLM toolkit that allows you to run LLMs and additional services. It consists of a CLI and a companion App that allows you to manage and run AI services with ease. Harbor is in essence a very large Docker Compose project with extra conventions and tools for managing it.

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

### Relevant Docs
- [Adding a new service](../docs/7.-Adding-A-New-Service.md)

## The Core Task: Hybrid Orchestration

The primary goal of this task is to solve a fundamental limitation for AI developers: running performance-sensitive services like LLMs natively on the host to get direct GPU access, while keeping other services (like web UIs or databases) conveniently containerized.

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

## Technical Architecture Deep Dive

### Composition Flow: Bash vs. Deno Pathways

Harbor has two composition pathways. This task focuses on making the modern Deno path feature-complete by using the legacy Bash path as a blueprint.

1.  **Legacy Bash Pathway (`__compose_get_static_file_list_legacy` in `harbor.sh`)**
    *   **Status**: Mature, feature-complete, but slower and harder to maintain.
    *   **Flow**:
        1.  `compose_with_options` is called with arguments like `-x ollama`.
        2.  It parses these arguments to create an `exclude_handles` array.
        3.  It calls `__compose_get_static_file_list_legacy`, passing the exclusion list.
        4.  This function iterates through all `compose.*.yml` files, performing the "Surgical Exclusion" logic (e.g., skipping `compose.ollama.yml` but keeping `compose.x.webui.ollama.yml`).
        5.  `compose_with_options` then manually adds the corresponding `ollama/ollama_native.yml`.
    *   **Relevance**: This is the **blueprint** for the correct logic that needs to be implemented in Deno.

2.  **Modern Deno Pathway (`routine_compose_with_options` -> `mergeComposeFiles.js`)**
    *   **Status**: Active default (`default_legacy_cli=false`), faster, but **functionally incomplete (the focus of this task)**.
    *   **Flow (Current & Broken)**:
        1.  `compose_with_options` is called. Due to the `default_legacy_cli` flag, it immediately calls `routine_compose_with_options`.
        2.  `routine_compose_with_options` **fails to parse** the `-x` flags. It passes all arguments raw to the Deno `mergeComposeFiles.js` routine.
        3.  The Deno `resolveComposeFiles` function in `docker.js` treats `-x` as a service name and has **no exclusion logic**.
        4.  The file discovery in `paths.js` only discovers `compose.*.yml` files, completely **ignoring `_native.yml` files**.
    *   **Required Fix**: The Deno routines (`mergeComposeFiles.js`, `docker.js`, `paths.js`) must be enhanced to parse arguments correctly and implement the full surgical exclusion and replacement logic, mirroring the Bash pathway.

### File Naming Conventions: The Core of the Logic

The entire hybrid orchestration system relies on a strict and meaningful file naming convention. Understanding this is critical.

*   `compose.<service>.yml`: **Container Definition**. This file defines how to run `<service>` in a container. It **MUST be excluded** when running natively.
    *   *Rationale*: Including this file would launch the container, creating a conflict with the native process and defeating the purpose of hybrid execution.
*   `compose.x.<svc1>.<svc2>.yml`: **Integration File**. This file defines how services connect (e.g., environment variables, network aliases). It **MUST be preserved** regardless of runtime mode.
    *   *Rationale*: The integration logic is essential for services to communicate, whether they are native or containerized. The `webui` container still needs to know how to find `ollama`.
*   `<service>/<service>_native.yml`: **Native Contract & Proxy**. This dual-purpose file is the key to the solution. It contains the lightweight proxy container definition (visible to Docker Compose) and the native process metadata in an `x-harbor-native` block (used by Harbor's scripts).
    *   *Rationale*: This file is **included as a replacement** for the excluded container definition, bridging the native process into the Docker ecosystem.
*   `compose.<service>.<capability>.yml`: **Capability File**. Adds functionality like `nvidia` GPU support. These are preserved as they are relevant to both runtimes.

### Key Data Structures

**Service Context Object (Bash):**

```bash
HANDLE='ollama'
IS_ELIGIBLE='true'
PREFERENCE='NATIVE'
RUNTIME='NATIVE'
NATIVE_EXECUTABLE='ollama'
NATIVE_DAEMON_ARGS=('serve')
NATIVE_PORT='11434'
NATIVE_PROXY_IMAGE='alpine/socat'
NATIVE_PROXY_COMMAND='TCP-LISTEN:{{.native_port}},fork TCP:host.docker.internal:{{.native_port}}'
```

**Native YAML Contract:**

```yaml
# ollama/ollama_native.yml
services:
  ollama:
    image: alpine/socat
    container_name: ${HARBOR_CONTAINER_PREFIX}.ollama
    command: TCP-LISTEN:${OLLAMA_HOST_PORT},fork TCP:host.docker.internal:${OLLAMA_HOST_PORT}
    ports: ["${OLLAMA_HOST_PORT}:${OLLAMA_HOST_PORT}"]
    # ... proxy container definition

x-harbor-native:
  executable: ollama
  daemon_args: [serve]
  port: ${OLLAMA_HOST_PORT}
  requires_gpu_passthrough: false
```

## The Implementation Plan

### Phase 1: Foundation & Schema ✅ COMPLETE
- [x] **Analyze current native service implementation** - Understand existing limitations and architecture
- [x] **Design new YAML schema** - Create `executable` and `daemon_args` fields for Docker-style patterns
- [x] **Update native contract files** - Implement new schema in example service (Ollama)
- [x] **Update native entrypoint scripts** - Support new execution patterns with validation
- [x] **Update Deno config parser** - Support both old/new formats, extract proxy config

### Phase 2: Core Orchestration Logic ✅ COMPLETE
- [x] **Update Harbor context building** - Use new array-based execution in Bash
- [x] **Implement Docker-style execution** - Proper argument handling and quoting
- [x] **Test basic native service lifecycle** - Start/stop/status tracking works
- [x] **Validate native service isolation** - Confirm services run independently

### Phase 3: Composition System Discovery & Analysis ✅ COMPLETE
- [x] **Map Harbor composition pathways** - Identify Deno vs Bash composition routes
- [x] **Analyze file discovery logic** - Understood how compose files are found and merged
- [x] **Identify composition gaps** - Discover missing native proxy integration
- [x] **Evaluate architectural approaches** - Compared different implementation strategies

### Phase 4: Enhanced Composition System ✅ COMPLETE
- [x] **Extend argument parsing** - Support exclusion flags (`-x`, `--exclude`) and service lists
- [x] **Enhance file discovery** - Include both `compose.*.yml` and `*_native.yml` files
- [x] **Map services to contracts** - Create service → native contract file mapping
- [x] **Implement exclusion logic** - Skip container definitions for native services
- [x] **Implement substitution logic** - Include native proxy definitions instead

### Phase 5: Proxy Container Integration 🔄 IN PROGRESS
- [x] **Generate proxy containers** - Basic proxy container generation implemented
- [ ] **Configure networking** - Ensure proper container-to-native communication
- [ ] **Implement health checks** - Validate native service availability through proxies
- [ ] **Ensure the .x. functionality works for native execution** - check if this involves compose files
- [ ] **Handle environment variables** - Pass native service configs to proxy containers

### Phase 6: Cross-Service Dependencies (NEXT)
- [ ] **Test hybrid scenarios** - Native + container services working together
- [ ] **Validate service discovery** - Containers can find native services via proxies
- [ ] **Test dependency chains** - Complex multi-service setups work correctly
- [ ] **Verify integration files** - Cross-service compose files (e.g., compose.x.webui.ollama.yml)

### Phase 7: Backward Compatibility & Robustness (FUTURE)
- [ ] **Ensure legacy support** - Old YAML contracts continue working
- [ ] **Handle edge cases** - Missing files, invalid configs, partial failures
- [ ] **Implement graceful degradation** - Fallback to container-only when native fails
- [ ] **Add comprehensive error handling** - Clear error messages and recovery paths

## Design & Architectural Record

The primary strategic decision for this task was: **How do we implement the missing hybrid orchestration logic in the default Deno pathway?**

Several options were considered:

1.  **Ad-hoc Deno Patches**: This involved quickly adding simple, non-systematic patches to the Deno code to handle exclusions.
    *   *Critique*: This approach was rejected because it would lead to significant technical debt, would not be maintainable, and would ignore the proven, correct logic already implemented in the Bash system. It's a quick fix that creates long-term problems.

2.  **Full Deno Rewrite from Scratch**: This involved ignoring the legacy Bash implementation and re-designing the entire composition logic in Deno from first principles.
    *   *Critique*: This was rejected as being too high-risk and time-consuming. The legacy Bash system, while complex, contains years of accumulated knowledge about edge cases and complex interactions. A full rewrite would likely re-introduce old bugs and delay the delivery of the core feature.

3.  **Port the Proven Logic from Bash to Deno (The Chosen Path)**: This strategy involves supporting both the legacy `__compose_get_static_file_list_legacy` and deno pathways. The current step in that task is to carefully port its "surgical exclusion" logic into the more modern, maintainable, and performant Deno routines (`resolveComposeFiles` in `docker.js`).
    *   *Rationale*: This is the optimal, low-risk, high-quality solution. It leverages the best of both worlds: the proven correctness of the legacy logic and the superior performance and maintainability of the Deno runtime. It ensures 100% backward compatibility in behavior while improving the underlying technology. This is a "surgical enhancement," not a blind rewrite.

## Best Practices & Gotchas

### General Best Practices for Harbor Development
1.  **Incremental Implementation**: Build and test one feature at a time.
2.  **Backward Compatibility First**: Ensure container-only workflows are never broken.
3.  **Fail Fast & Clear**: Provide actionable error messages.
4.  **Separation of Concerns**: Keep argument parsing, file resolution, and merging as distinct, testable steps.
5.  **Idempotency**: Operations like `harbor up` should be safely repeatable.
6.  **Comprehensive Logging**: Use `log_debug` and `log_info` to trace the composition process.
7.  **Defensive Programming**: Validate inputs (service names, file paths) at every stage.
8.  **Minimal Impact Principle**:
        - Make the **smallest possible changes** to achieve maximum functionality
        - **Preserve existing behavior** for all non-exclusion scenarios
        - **No breaking changes** to public interfaces where avoidable

### Task-Specific Best Practices & Gotchas
1.  **Surgical Exclusion is Key**: Do not use broad `includes()` checks for exclusion. The logic must match `compose.<service>.yml` exactly to avoid excluding integration files.
2.  **Deno's CWD**: The Deno routines run from `harbor_home`. All file paths must be resolved relative to this root. Use `path.join()` for safety.
3.  **Bash Array Quoting**: When passing arguments from Bash to Deno, and when constructing `eval`-safe context strings, always use `printf %q` to handle special characters correctly.
4.  **Argument Parsing Order**: Harbor's CLI passes arguments in a specific order (`-x` flags, then `--`, then services and capabilities). The Deno parser must respect this structure.
5.  **Template Resolution**: Variables in native contracts (like `{{.native_port}}`) are resolved by the Bash layer, not the Deno layer. The Deno layer should treat them as opaque strings.



## Meta-Instructions for AI Assistants (Copilot Guide)

### Core Mental Model for Harbor
*   **Harbor is a meta-orchestrator.** It doesn't just run Docker Compose; it *builds* the configuration dynamically before running it. Your primary focus is on this generation process.
*   **Think in layers**: User Command → Bash Orchestration → Deno Composition → Docker Runtime. A bug could be in any layer.
*   **The file system is the database**: The state and capabilities of the system are defined by the presence and naming of `.yml` files.

### The Iterative Design Process
When faced with a complex problem, follow this structured thinking process:
1.  **High-Level Plan**: State the goal and break it into phases.

2.  **Concrete Options**: Propose 3-5 distinct, concrete implementation options. Use code snippets.
3.  **Harsh Critique**: Constructively critique each option against best practices (general and task-specific). Identify flaws, risks, and tradeoffs.
4.  **Cross-Pollinate & Synthesize**: Create 1-3 new, higher-quality solutions by combining the best aspects of the initial options and addressing their critiques.
5.  **Decision**: Choose the best synthesized solution and justify why it's optimal in terms of risk, maintainability, and meeting requirements.
6. **Bookkeeping**: Keep track of your task progress by writing out the what, why, and how of steps you have:
   1.  completed,
   2.  are currently working on,
   3.  expect to do next,
   4.  what changes have been made to the original plan and why, and
   5.  critique your edits periodically to ensure they are in line with best practices and your goals.
   6.  periodically update copilot_harbor_native_service_task_copilot_guide_plan_and_progress.md

#### The Development Workflow
1.  **`BEFORE` making changes**:
    *   **Trace the full data flow**: From `harbor up` to the final `docker compose` command.
    *   **Identify the active pathway**: Are we in the legacy Bash path or the modern Deno path? (Check `default_legacy_cli`).
    *   **Review file conventions**: Remind yourself of the purpose of `compose.<service>.yml` vs. `compose.x.*.yml`.
2.  **`WHILE` making changes**:
    *   **Make targeted edits; do not regenerate large files.** For files longer than ~500 lines (like `harbor.sh`), identify the specific functions to modify. Do not ask the assistant to rewrite the entire file, as this increases the risk of regressions and loses context. Provide the specific function to be replaced.
    *   **Follow existing patterns**: If a file uses functional style, use functional style. If it uses procedural, do the same, maintain existing documentation, maintain existing features, keep it backwards compatible, maintain existing functionality.
    *   **Add logging**: Use `log_debug()` to trace your changes. It's better to log too much than too little.
3.  **`AFTER` making changes**:
    *   **Test both primary and secondary paths**: Ensure `harbor up webui` (container-only) still works perfectly. Then test `harbor up -x ollama webui` (hybrid).
    *   **Check for regressions**: Use `git diff` to review your changes and ensure you haven't unintentionally broken something.
    *   **Think as the main author**: Would these changes be accepted in a pull request? Is the code clean, documented, and maintainable?

## Appendix: Quick Reference

### Key Files for This Task
*   `harbor.sh`: `routine_compose_with_options()` - The Bash-to-Deno bridge.
*   `routines/mergeComposeFiles.js`: The Deno entrypoint for composition; where argument parsing happens.
*   `routines/docker.js`: `resolveComposeFiles()` - The core file resolution and exclusion logic.
*   `routines/paths.js`: `listComposeFiles()` - File discovery logic.
*   `ollama/ollama_native.yml`: The canonical example of a native service contract.

### Key Testing Commands
*   **Regression Test (Container-only)**: `harbor up webui`
*   **Hybrid Test**: `harbor up -x ollama webui`
*   **Direct Deno Test**: `deno run -A routines/mergeComposeFiles.js -x ollama -- webui ollama`
*   **Dry Run (View composed file)**: `harbor up -x ollama webui --dry-run > debug.yml`

---

**Last Updated:** 2025-06-20
**Next Review:** After Phase 4 completion
**Document Version:** 3.0