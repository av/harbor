---
name: bughunt
description: Fully autonomous bug hunting pipeline — discover bugs in a scoped area using parallel subagents, independently triage each finding, fix confirmed issues with subagents, then audit all fixes against repo constraints and target platforms. Runs end-to-end without user interaction.
---

# Bughunt

Fully autonomous pipeline: find, triage, fix, and audit bugs in a scoped area of a codebase. Five phases, each using subagents to parallelize work and provide independent assessments.

**This skill runs end-to-end without asking the user any questions.** Do not pause for confirmation, approval, or input between phases. Make autonomous decisions at every step — section splits, severity judgments, fix strategies, conflict resolution. Log progress to the report so the user can review the final output, but never block on user input.

## Parameters

| Parameter | Default | Example override |
|-----------|---------|-----------------|
| **Scope** | _(required)_ | `the install script`, `src/auth/`, `the CLI argument parser` |
| **Sections** | auto-split from scope | `split by platform`, `one per module` |
| **Platforms** | inferred from repo | `Linux, macOS, WSL` |
| **Output** | `/tmp/bughunt-output/` | `Output directory: ./qa/` |

## Workflow

```
1. Orient       Read the target code, identify natural section boundaries
2. Discover     Parallel bugbash subagents, one per section
3. Triage       Independent subagent per finding — confirm, dispute, or adjust severity
4. Fix          Subagent per confirmed issue — investigate, implement, self-review
5. Audit        Verify all fixes against repo constraints and target platforms
```

## Phase 1 — Orient

Read the target files yourself. Identify section boundaries for parallel discovery. Do not delegate this phase — you need the full picture to write good subagent prompts in later phases.

Good splits follow the code's own structure:
- **Per platform/backend** — if the code branches by OS, distro, or provider
- **Per layer** — argument parsing, core logic, error handling, output formatting
- **Per module** — one subagent per file or logical unit

Write the section list and file ranges, then proceed immediately to Discovery. Each section needs enough context in isolation for a subagent to reason about it.

Create the output directory and initialize the report:

```bash
mkdir -p {OUTPUT_DIR}/evidence
```

## Phase 2 — Discover

Launch one subagent per section using the Agent tool, all in parallel (send all Agent calls in a single message). Each subagent:

1. Reads the code for its section
2. Looks for real bugs — not style nits, not hypotheticals
3. Returns structured findings

### Subagent prompt template

> You are bugbashing [project]. Your section is **[section name]** in `[file path]`.
>
> Read the file and focus on [specific areas and line ranges].
>
> For each real bug, provide:
> - **Issue ID** (e.g., SEC-001)
> - **Severity** (Critical/High/Medium/Low)
> - **Description**
> - **File:Line**
> - **Repro scenario**
> - **Evidence** (code snippet)
> - **Expected vs Actual**
>
> Only report bugs a real user could hit — no style nits or hypotheticals.

### After all discovery agents return

Compile findings into the report. Deduplicate issues reported by multiple sections. Assign each a canonical ID. Update summary counts. Proceed immediately to Triage — do not wait for user input.

## Phase 3 — Triage

Launch one subagent per finding using the Agent tool, all in parallel (send all Agent calls in a single message). Each triage agent:

1. Reads the relevant code fresh (no access to the discovery agent's reasoning)
2. Independently assesses whether the bug is real
3. Checks preconditions — are they realistic or contrived?
4. Evaluates severity — does it match the claimed impact?
5. Returns a short verdict

### Triage subagent prompt template

> You are an independent triage reviewer. Read the code, assess whether the bug is real.
>
> **Finding [ID] (claimed [severity]):** [one-paragraph description with file:line]
>
> Read `[file]` lines [range]. Answer:
> 1. Is this a real bug? Can a user actually hit it?
> 2. What preconditions are required? How likely are they?
> 3. Is [severity] the right severity?
> 4. Are there mitigating factors the original report missed?
>
> Return a short verdict: CONFIRMED / DISPUTED / DOWNGRADE with reasoning (under 200 words).

### Verdicts

- **CONFIRMED** — bug is real at the stated severity. Proceeds to fix.
- **DOWNGRADE** — bug is real but severity is wrong. Adjust and keep if still actionable.
- **DISPUTED** — bug is not real, requires impossible preconditions, or has zero practical impact. Drop from the report.

Update the report with triage results. Proceed immediately to Fix — do not wait for user input.

## Phase 4 — Fix

Launch one subagent per confirmed issue using the Agent tool, all in parallel (send all Agent calls in a single message). Each fix agent:

1. Reads the relevant code and surrounding context
2. Investigates the root cause (not just the symptom)
3. Implements the minimal correct fix
4. Self-reviews the fix against specific criteria
5. Returns the exact edit (old_string / new_string) — does NOT apply it

### Fix subagent prompt template

> You are fixing a confirmed [severity] bug in `[file]`.
>
> **Bug [ID]:** [description]
>
> Read [file] lines [range].
>
> Fix requirements:
> - [specific behavioral requirements for this fix]
> - Keep the fix minimal — don't restructure surrounding code
>
> Return: the exact `old_string` and `new_string` for an Edit tool call. Include enough surrounding context to make the match unique.
>
> Self-review: after writing the fix, re-read it and check:
> 1. [fix-specific verification questions]
> 2. Does the fix handle the error/edge case that triggered the bug?
> 3. Does it introduce any new failure modes?

### Why agents return edits instead of applying them

Multiple agents may edit the same file. Applying edits in parallel causes conflicts. Instead, collect all proposed edits, review them for overlap, then apply sequentially.

### After all fix agents return

1. Check for overlapping edits in the same file — resolve conflicts autonomously (prefer the fix for the higher-severity issue; if equal, keep the more minimal edit)
2. Apply edits sequentially, one file at a time
3. Run syntax/parse checks on every modified file (`bash -n`, `python -m py_compile`, `tsc --noEmit`, etc.)
4. Proceed immediately to Audit — do not wait for user input

## Phase 5 — Audit

Verify every fix against repo-level constraints. This is where platform-specific bugs, lint violations, and convention breaks get caught.

### 5a. Discover constraints

Before auditing, identify what constraints exist in the repo:

- **Lint rules** — project linters, custom rules, CI checks
- **Target platforms** — which OS/arch/runtime must the code support?
- **Portability rules** — POSIX vs GNU, shell compatibility, min language versions
- **Conventions** — error handling patterns, logging style, naming

Sources: CI configs, linter configs, CLAUDE.md, CONTRIBUTING.md, Makefile targets, existing lint rules/fixtures.

### 5b. Audit each fix

For each fix, check:

1. **Lint** — run the project's linter on modified files. If it has custom rules, check those specifically.
2. **Platform portability** — trace every command, flag, and function call in the fix. Verify availability on all target platforms. Common traps:
   - GNU-only flags (`head -c`, `readlink -f`, `grep -P`, `sed -i` without backup suffix)
   - macOS BSD vs GNU coreutils differences
   - bash-isms in code that runs under `/bin/sh`
   - Commands missing in minimal/container environments (`timeout`, `getent`, `sudo`)
3. **Convention match** — does the fix follow the patterns used in surrounding code?
4. **Interaction** — do any fixes conflict with each other when applied together?

### 5c. Fix audit failures

If a fix fails the audit:
1. Identify the exact constraint violation
2. Determine the portable/correct alternative
3. Apply the correction directly (no subagent needed for mechanical replacements)
4. Re-run the relevant check to confirm

## Guidance

- **Fully autonomous.** Run all five phases without stopping for user input. Make every decision yourself — section splits, severity calls, fix strategies, conflict resolution, audit judgments. The user reviews the final report, not intermediate checkpoints.
- **Subagents are your primary tool.** Use the Agent tool aggressively. Every phase after Orient must use parallel subagents. Launch all subagents for a phase in a single message to maximize parallelism. Do not do sequentially what subagents can do in parallel.
- **Subagents are independent.** Each subagent sees only its prompt and the code it reads. It has no memory of other phases or other agents. Write prompts that are fully self-contained.
- **Discovery is broad, triage is adversarial.** Discovery agents should cast a wide net. Triage agents should be skeptical — their job is to kill false positives, not confirm findings.
- **Fixes are minimal.** A fix agent should change the fewest lines possible to resolve the confirmed bug. No cleanup, no refactoring, no "while I'm here" improvements.
- **The audit catches what agents miss.** Agents don't have cross-platform knowledge baked in. The audit phase exists specifically to catch platform-specific mistakes, lint violations, and convention breaks that individual fix agents can't know about.
- **Report incrementally.** Update the report after each phase completes. If the session is interrupted, the work so far is preserved.
- **Log, don't ask.** Write findings, triage verdicts, fix summaries, and audit results into the report as you go. The user reads the final report — they do not participate during execution.
