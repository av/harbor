---
name: facts-implement
description: >
  Operate on @spec facts — implement them in code, then tag @implemented.
  Use when asked to implement facts, implement the spec, build from the
  fact sheet, make facts true, or work through unimplemented requirements.
---

# facts-implement

You are a fact-driven implementer. Your job is to take `@spec` facts and implement them in code — systematically, in a single session. This is the `@spec → @implemented` lifecycle transition.

## Goal

Each `@spec` fact is a precise, actionable requirement. Implement all `@spec` facts, using subagents to parallelize independent work where possible. Mark completed facts by transitioning them from `@spec` to `@implemented`. If you cannot complete all facts, report exactly what remains and why.

**Important:** Only implement `@spec` facts. `@draft` facts are not yet refined — they need the `facts-refine` skill first. Untagged facts are already true. If you see facts without lifecycle tags that aren't implemented, classify them or suggest running `facts-discover` first.

## Process

### 1. Load the full spec

Run `facts list` to see the entire specification. Read and understand all facts — you need the full picture to make good ordering and grouping decisions, even though you will only implement unimplemented facts.

### 2. Identify remaining work

Run `facts check` to see which command-facts pass and which fail. This also validates the fact sheet structure (lint errors abort check early).

Run `facts list --tags "spec"` to see facts ready to implement. This is your implementation target.

Cross-reference: a `@spec` fact may already pass its validation command. If `facts check` shows it passing, verify the implementation is complete and transition it — do not re-implement.

### 3. Plan

Read through the unimplemented facts and decide on an implementation order. Use your judgment — consider dependencies between facts, section grouping, and what will unblock the most progress. There is no fixed ordering formula; you understand the codebase and the spec.

Group facts that can be implemented independently into parallel batches. Facts that depend on each other must be sequential.

### 4. Implement

For each fact:

1. Read the label — it states what must be true
2. Write the code that makes it true
3. If it has a validation command, that command is the test — run it to confirm (exit 0 = done)
4. If it has no validation command, use your judgment: read the code, verify the behavior, be confident before proceeding
5. Transition it from `@spec` to `@implemented`:

```
facts edit <id> --remove-tag "spec" --add-tag "implemented"
```

Use subagents to implement independent facts in parallel. Each subagent should:
- Receive the specific facts it is responsible for (IDs, labels, commands)
- Have enough context about the overall spec and codebase to make good decisions
- Run validation commands and tag facts as implemented
- Report back what it completed and any issues encountered

### 5. Verify

After all implementation work is done, run:

```
facts check
```

All command-facts should pass. Then confirm no `@spec` facts remain:

```
facts list --tags "spec"
```

If any `@spec` facts remain, report them with a clear explanation of what blocked progress.

### 6. Handle problems

**Ambiguity:** prefer the more specific fact. If two facts genuinely conflict, implement the one with a validation command over the one without — objective criteria take priority. If you cannot resolve it, skip and report.

**Impossible facts:** skip them, do not tag as implemented, report the issue.

**Broken validation commands:** if a fact's command has a typo or wrong path, fix it with `facts edit <id> --command "corrected command"` before implementing.

## Guidelines

- Do not modify fact labels, structure, or section organization. Only add `@implemented` tags and fix broken commands.
- Respect the section structure — it often mirrors the intended code architecture.
- Validation commands are the tests. If a fact has a command, that is how you verify it. Do not write separate tests unless the fact specifically requires them.
- Facts without commands require your judgment. Be conservative — only tag as `@implemented` when you are confident the code satisfies the requirement.
- If implementing a fact requires adding a dependency, do so. The fact sheet is the authority.
- Commit after coherent batches of work.

## Example session

```
# Load full spec
facts list

# See current state
facts check
facts list --tags "spec"

# Implement foundational @spec facts first
# Fact "x1z" @spec: project uses SQLite for storage
# -> Add sqlx dependency, create database module
# -> Run: facts check (confirms x1z passes)
facts edit x1z --remove-tag "spec" --add-tag "implemented"

# Spawn subagents for independent @spec facts:
# Subagent 1: "a2b" (users table schema) + "c3d" (GET /users endpoint)
# Subagent 2: "e4f" (auth middleware) + "g5h" (session handling)

# After subagents complete, verify everything
facts check
facts list --tags "spec"  # should be empty or explained
```
