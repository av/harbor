---
name: bugbash
description: Systematically explore and test any software project (CLI, API, Backend, Library, etc.) to find bugs, usability issues, and edge cases. Produces a structured report with full reproduction evidence (exact commands, inputs, logs, and tracebacks) for every issue.
---

# Bugbash (General Software)

Systematically explore a software project, find issues, and produce a report with full reproduction evidence for every finding. This skill applies to CLIs, APIs, Backends, Libraries, and other non-web interfaces.

## Setup

Identify the **Target** (e.g., a CLI binary, an API base URL, a Python package).

| Parameter | Default | Example override |
|-----------|---------|-----------------|
| **Target** | _(required)_ | `./my-cli`, `http://localhost:8080`, `import mylib` |
| **Output directory** | `/tmp/dogfood-output/` | `Output directory: ./qa-reports` |
| **Scope** | Full project | `Focus on the auth middleware` |

## Workflow

```
1. Initialize    Set up output dirs, report file, build/start the software
2. Orient        Discover surface area (help menus, API schemas, exported functions)
3. Explore       Systematically test features, inputs, and edge cases
4. Document      Record exact inputs, outputs, and logs for each issue
5. Wrap up       Update summary counts, finalize report
```

### 1. Initialize

```bash
mkdir -p {OUTPUT_DIR}/logs {OUTPUT_DIR}/evidence
```

Create a `report.md` in the output directory and fill in the header fields. Include:
- Target
- Date
- Environment Details (OS, language version)
- Summary Counts (Critical, High, Medium, Low)

If the software needs to be built or started (e.g., `npm run build`, `docker-compose up`, `cargo build`), do that now. Keep track of the startup logs and run servers in the background if necessary (e.g., using `&` and redirecting output).

### 2. Orient

Map out the surface area of the software before testing.

- **For CLIs:** Run `{TARGET} --help`, list subcommands, check environment variable configurations.
- **For APIs:** Fetch OpenAPI/Swagger specs, list route definitions in code, or run a schema discovery tool.
- **For Libraries:** Inspect exported modules, classes, and public methods.

Save this initial mapping to `{OUTPUT_DIR}/surface-area.txt`.

### 3. Explore

Work through the surface area systematically.

- **Happy Paths:** Test the primary use cases. Does it do what it claims to do?
- **Invalid Inputs:** Pass wrong types, extremely large strings, negative numbers, malformed JSON.
- **Missing Context:** Run commands without required environment variables, missing config files, or unauthenticated API calls.
- **Boundary Conditions:** File not found, permission denied, port already in use.

**At each step:**
Capture standard output, standard error, exit codes, and HTTP status codes.

### 4. Document Issues (Repro-First)

Document issues *as you find them*. Do not wait until the end. Every issue must be reproducible by a human reading the report.

For each issue, capture:
1. **Description:** What is the bug or UX issue?
2. **Severity:** Critical (crash/data loss), High (broken core feature), Medium (broken edge case), Low (UX issue/typo).
3. **Repro Steps:** Exact commands run, API requests made (e.g., `curl` commands), or code executed.
4. **Expected vs Actual Behavior:** What should have happened vs what actually happened.
5. **Evidence:**
   - Stdout/Stderr output
   - Stack traces or panic messages
   - Log file snippets
   - Exit codes

Save verbose evidence (like full crash dumps or multi-megabyte log files) to `{OUTPUT_DIR}/evidence/issue-{NNN}.txt` and reference it in the report. For short errors, embed them directly in the report using markdown code blocks.

### 5. Wrap Up

Aim to find **5-10 well-documented issues**. Depth of evidence matters more than total count — 5 issues with full repros beat 20 with vague descriptions.

After exploring:
1. Re-read the report and update the summary severity counts so they match the actual issues. Every issue block must be reflected in the totals.
2. Stop any background processes (e.g., API servers) started during initialization.
3. Tell the user the report is ready and summarize findings: total issues, breakdown by severity, and the most critical items.

## Guidance

- **Repro is everything.** Every issue needs proof. Provide the exact `curl` command, CLI invocation, or script used to trigger the bug. A reader should be able to copy-paste the commands to see the exact same failure.
- **Verify reproducibility.** Before documenting an issue, verify it is reproducible with at least one retry. If it's flaky, note that and try to identify the conditions.
- **Capture the environment state.** Often bugs depend on the environment (files present, variables set). Note `pwd`, env vars, or local files if they are part of the repro.
- **Write findings incrementally.** Append each issue to the report as you discover it. If the session is interrupted, findings are preserved. Never batch all issues for the end.
- **Don't just look for crashes.** Usability matters. Confusing error messages, undocumented required flags, and sluggish performance are all valid issues.
- **Test like a user, not a robot.** Try common workflows end-to-end. Combine flags or API calls in ways a real user would, passing the output of one command as input to the next.
- **Check the exit codes and status codes.** A CLI returning `0` on failure, or an API returning `200 OK` for an error payload, is a bug. `echo $?` or `curl -w "%{http_code}"` are your friends.
