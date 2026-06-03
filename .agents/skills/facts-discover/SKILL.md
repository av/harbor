---
name: facts-discover
description: >
  Scan the codebase and classify every fact by lifecycle stage — tag
  @draft, @spec, or @implemented based on what the code actually shows.
  Add missing facts, fix inaccurate ones, remove obsolete ones. Use when
  asked to discover facts, bootstrap or update a fact sheet, scan the
  codebase for truths, sync facts to match the code, or audit the fact
  sheet for accuracy.
---

# facts-discover

You are a fact sheet maintainer. Your job is to scan the codebase, classify every fact by lifecycle stage, and add missing truths — in a single session.

**Tip:** Short CLI aliases are available and recommended for high-frequency operations: `ll` (list --light), `at <id> <tag>` (quick --add-tag), `rt <id> <tag>` (quick --remove-tag), `rm`, and `ls`. All extra arguments are forwarded. See `facts --help` or `facts skills show facts`.

## When to use this skill

This skill classifies facts and syncs the fact sheet with reality. **Only use when the user explicitly asks to discover, audit, or sync facts.** If the user says "work on facts" or "add facts", they want to define spec — use the `facts` skill instead, not this one.

## Goal

After running this skill, every fact should have the correct lifecycle tag:

- **`@draft`** — the fact is vague or high-level; needs refinement before it can be implemented (e.g. "this project supports stripe payments")
- **`@spec`** — the fact is precise and actionable, but the code doesn't back it up yet (e.g. "POST /payments creates a Stripe PaymentIntent and returns the client secret")
- **`@implemented`** — the fact is true and the codebase proves it
- **Untagged** — ground truth discovered from the codebase; already verified by observation

Additionally, add facts about important truths not yet in the fact sheet (these go in untagged, since they're already true), fix inaccurate facts, and remove obsolete ones.

Facts with good validation commands are self-enforcing — they catch regressions automatically. But **a manual fact is better than a fact with a useless command.** A command that always passes regardless of whether the fact is true gives false confidence and is worse than no command at all. Only add a command when it genuinely tests the claim.

## Process

### 1. Load the current fact sheet

Run `facts list` to see all current facts. Note which sections exist and what they cover.

Run `facts check` to see which command-facts pass and which fail. Failing facts are candidates for removal or correction.

For each manual fact (`?` in the output): read what it claims, check the relevant code, and classify it based on what you actually find — not on the label alone. Manual facts are often the most important ones because they describe behavior that resists simple command validation.

### 2. Scan the codebase

Build a mental model of the project by tracing what it **does**, not just how it's structured. Focus on end-user-visible behavior — the features, workflows, and contracts that someone using or integrating with this project would care about.

Use subagents to scan different areas in parallel for large codebases. Assign each subagent a **feature area or module**, not a structural category like "dependencies" or "build system." For each area, the subagent should answer:

- **What does this do?** — describe the behavior from the user's perspective
- **What are the inputs and outputs?** — API contracts, CLI flags, file formats, event shapes
- **What are the edge cases?** — error handling, boundary conditions, fallback behavior
- **What would break if this were reimplemented naively?** — non-obvious invariants, ordering dependencies, timing constraints, implicit contracts between components
- **What are the key concepts?** — named types, domain abstractions, data structures. What does this module call things, and how do those names relate to concepts in other modules?

Each subagent should report back **behavioral observations** — not "this file exists" or "this uses library X", but "when X happens, Y results" and "if X fails, the system does Y."

Do not waste facts on structural trivia. "The project has a src/auth.rs file" is not a useful fact. "Expired tokens are rejected with 401 and the response includes a `reason` field" is.

### 2b. Build the project ontology

Before classifying or writing facts, establish the project's key entities and relationships as facts in a `## domain` section of the main `.facts` file. This vocabulary becomes the canonical naming for all other facts in the sheet.

1. From the subagent scan results, identify the named concepts that appear across multiple parts of the codebase — these are the project's entities.
2. For each entity, write a definition fact using the pattern `a <Name> is <definition>`. Use the name the codebase actually uses (the struct name, the type name, the term in the docs), not an invented abstraction.
3. Identify the important relationships between entities — what contains what, what produces or consumes what, what validates or transforms what. Write these as relation facts using the defined entity names in natural declarative statements. There is no rigid grammar — the connection should be specific and use entity names consistently.
4. Check the existing fact sheet for inconsistent terminology. If the same concept is called "sheet" in one fact and "fact file" in another, standardize on one term and edit the inconsistent facts.

If a `## domain` section already exists, update it — add missing entities, remove obsolete ones, correct inaccurate definitions. The domain section evolves with the codebase.

**Quality filters:**

- Only define entities that appear as concepts across multiple areas of the codebase. If a concept is confined to a single function and won't appear in other facts, it doesn't need a domain definition. After writing behavioral facts in Steps 3–4, prune any domain entity that turned out to be unreferenced.
- Relations capture the topology — the wiring diagram between entities that you can't see from individual behavioral facts. A domain section with only entity definitions and zero relations is a parts list without assembly instructions. If you defined entities, ask: how do they connect? What produces, consumes, contains, or transforms what?
- Use the actual names from the code. If the codebase calls it `FactSheet`, the fact uses `FactSheet`. Do not normalize to "Fact Sheet" unless the project's own documentation does.
- A domain section typically has 5–15 entities and a handful of relations. If you're defining 20+ entities, you are likely including implementation details rather than domain concepts. If no concepts pass the cross-cutting threshold, skip the domain section entirely — not every project needs one.

For projects that split facts across multiple files (`cli.facts`, `api.facts`), the `## domain` section goes in the main `.facts` file since it applies project-wide.

**Example** (for a payment processing project):

```
## domain
- a PaymentIntent is a Stripe object representing a single charge attempt
- a Webhook is an incoming HTTP POST from Stripe reporting a payment event
- a DeadLetter is a Webhook that exhausted all retry attempts without acknowledgement
- a Merchant is a registered business account that receives payments
- a PaymentIntent produces Webhooks on status changes
- a Webhook becomes a DeadLetter after 3 failed delivery attempts
- a Merchant owns PaymentIntents
```

**Anti-example** (what not to write):

```
## domain
- a Rust source file contains module definitions
- parser.rs is responsible for parsing
- the project has a CLI that accepts commands
```

These are structural trivia that restate file existence, not domain concepts.

### 3. Classify facts by lifecycle stage

For each existing fact, check it against the codebase and assign the correct lifecycle tag:

- **True and code-backed** → tag `@implemented`: `facts edit <id> --add-tag "implemented"`
- **Precise and actionable, but code doesn't exist yet** → tag `@spec`: `facts edit <id> --add-tag "spec"`
- **Vague or high-level, not yet actionable** → tag `@draft`: `facts edit <id> --add-tag "draft"`
- **Partially true** — edit the label first, then classify: `facts edit <id> --label "corrected statement"`
- **False or obsolete** — remove: `facts remove <id>`
- **Missing validation** — the fact could be verified by a command but lacks one: `facts edit <id> --command "check command"`

When a fact already has a lifecycle tag, verify it's still correct. An `@implemented` fact whose code was removed should be reclassified to `@spec`. A `@draft` fact that was refined elsewhere should be updated.

When removing facts, check if the concept has evolved rather than disappeared — edit instead of remove+add when the same idea persists in a new form.

When editing fact labels, use the vocabulary established in `## domain`. If a fact says "file" but the domain section defines the concept as "FactSheet", update the label to use "FactSheet" for consistency.

### 3b. Add commands to manual facts

Go through manual facts and ask: **can this be checked with a short shell command that would actually fail if the fact became false?**

That second part is the hard filter. Before adding a command, apply this test:

> If someone changed the codebase so this fact was no longer true, would the command fail?

If the answer is no — or only maybe — leave the fact manual.

#### What makes a command meaningful

A command validates a fact when it checks the **claim itself**, not just the existence of related code. The command should be:

- **Falsifiable** — would actually break if the fact became untrue
- **Fast** — runs in under a second (grep, test, jq, wc, head)
- **Idempotent** — read-only, no side effects
- **Stable** — does not break on unrelated changes (avoid line-count checks, match patterns not positions)
- **Silent on success** — exit 0 means the fact holds, non-zero means it doesn't

Good commands check concrete, specific things:

```sh
# Dependency exists in manifest
grep -q '^clap' Cargo.toml
grep -q '"express"' package.json

# File or directory exists
test -f tests/cli.rs
test -d src/components

# A specific value or setting in config
jq -e '.scripts.test' package.json >/dev/null
grep -q 'edition = "2024"' Cargo.toml

# Build or test suite passes
cargo build --quiet 2>/dev/null
npm test --silent

# A property holds (or does not hold) across the codebase
! grep -rq 'unsafe' src/
! grep -rq 'unwrap()' src/handlers/

# Count-based invariants (use ranges, not exact numbers)
test $(find src -name '*.rs' | wc -l) -ge 10

# Behavioral test — actually exercise the tool
facts list --help 2>&1 | grep -q '\-\-section'
echo '- test fact' | facts lint /dev/stdin 2>/dev/null
```

#### What makes a command useless

The most common failure mode is **keyword grepping**: picking a word from the fact label and checking that it appears somewhere in a source file. This doesn't validate the fact — it validates that the codebase uses similar vocabulary.

```sh
# BAD: "heading depth maps to hierarchy"
grep -q "depth" src/parser.rs
# This checks that the word "depth" appears in the file. It would pass
# even if depth handling was completely broken. It would fail if someone
# renamed the variable to "level" even though the behavior is unchanged.

# BAD: "tags are freeform tokens for filtering and categorisation"
grep -q "tags" src/model.rs
# The word "tags" will always be in a file that deals with tags.
# This tells you nothing about whether they're freeform or used for filtering.

# BAD: "commands run sequentially"
! grep -q "async\|tokio" src/check.rs
# Absence of async doesn't prove sequential execution — there are other
# ways to run things concurrently. And this would still pass if someone
# added parallelism via std::thread.

# BAD: "the CLI treats sections as first-class citizens"
grep -q "section" src/list.rs
# What does this even check? That the word "section" appears? Of course it does.
```

The pattern to watch for: if your command is `grep -q "<keyword from the fact>" <file that obviously contains that keyword>`, it's not a real check. Stop and either find a meaningful command or leave the fact manual.

#### When to leave facts manual

Not every fact can or should have a command. Leave facts manual when they are:
- **Subjective or qualitative** — "extreme simplicity", "codebase is DRY", "polished UX"
- **About human processes** — "bump version, commit, push"
- **About external systems** you can't query locally
- **About behavior** that would require a complex integration test to verify and is already covered by the project's test suite
- **About design intent** — "each fact is atomic and independent", "file order is canonical"
- **Only checkable via keyword grep** — if the only command you can write checks for a keyword rather than the actual claim, leave it manual

A fact sheet with 30 genuinely validated facts and 20 honest manual facts is far more useful than one with 50 commands that are all `grep -q "<word>" <file>`.

### 4. Add missing facts

Identify important behaviors and features not yet captured. Prioritize in this order:

1. **User-facing behaviors** — what can someone do with this project? What happens when they do it? What happens when they do it wrong?
2. **Contracts between components** — how do modules communicate? What does each one promise to the others?
3. **Edge cases and error handling** — what breaks, how, and what does the user see?
4. **Structural/architectural facts** — only when they constrain behavior (e.g. "single-threaded, so handlers cannot block" matters; "uses the clap crate" rarely does)

```
# Good — captures behavior a rewrite must preserve
facts add "uploading a file larger than 10MB returns 413 with a human-readable error" --section api/upload
facts add "duplicate messages within the 5-minute dedup window are silently dropped; the first is kept" --section processing/dedup
facts add "when the database is unreachable, queued writes retry 3 times with exponential backoff" --section resilience

# Bad — structural trivia that wastes space and tells an agent nothing useful
facts add "the project uses PostgreSQL for persistence" --section architecture
facts add "tests are in the tests/ directory"
facts add "the CLI is written in Rust"
```

Prefer facts that are:
- **Behavioral** — describes what happens, not what exists
- **Atomic** — one truth per fact
- **Falsifiable** — you could imagine a broken implementation where this fact would not hold
- **Worth preserving** — if someone rewrote this project from scratch using only the fact sheet, would this fact help them get the behavior right?

A fact sheet with 40 precise behavioral facts is more useful than one with 200 structural observations. If your fact sheet is growing past ~80 facts in a single file, split into focused files (`api.facts`, `cli.facts`) and prune structural filler.

When writing new facts, use the entity names from the `## domain` section. Consistent vocabulary across the fact sheet helps agents build an accurate mental model. If you find yourself using a term that does not appear in `## domain`, either add it there first or use the existing term instead.

### 5. Organize

Group related facts into sections using `--section`. Section paths support nesting (e.g. `api/auth`, `cli/subcommands`). Keep sections focused — split broad ones.

### 6. Validate and report

Run `facts check` to confirm all command-facts pass (this also lints the files).

Report what changed: facts added, edited, removed, commands added. If any areas of the codebase were ambiguous or couldn't be fully captured, say so.

## Guidelines

- Keep fact labels concise and declarative.
- **Command quality matters more than command count.** A command that doesn't actually test the fact is worse than no command — it creates false confidence. Only add commands that would break if the fact became false.
- When writing check commands, prefer `grep -q`, `test -f`, `test -d`, `jq -e`, and similar fast read-only checks. Avoid commands that build, install, or modify anything unless that is the point of the fact (e.g. "project builds successfully").
- Use tags to categorize when useful (e.g. `@ci`, `@api`, `@core`). Use `--add-tag` and `--remove-tag` for incremental tag changes.
- Sections with no remaining facts are cleaned up automatically by the CLI.
- **Lifecycle classification is the primary job.** Every fact should end up with the right lifecycle tag (`@draft`, `@spec`, `@implemented`) or no tag (ground truth). Do not remove `@draft` or `@spec` facts — classify them, don't delete aspirational work.
- When adding new facts you discovered from the codebase, leave them untagged — they are already true by observation.
- **Behavioral facts over structural ones.** When choosing what to add, ask: "would an agent reimplementing this project need to know this to get the behavior right?" File existence and dependency names are in the manifest. Deduplication logic, error responses, retry semantics, and edge cases are the things that get silently dropped in a rewrite — those are the facts worth writing.
- **Establish vocabulary before writing facts.** The `## domain` section defines the project's key entities and relations. Use those names consistently throughout the fact sheet. If you find yourself using a new term that does not appear in `## domain`, either add it there or use the existing term instead.

## Example session

```
# Load current state
facts list
facts check

# Spawn subagents to scan the codebase by feature area:
# Subagent 1: user authentication — login, signup, session handling, token lifecycle
# Subagent 2: payment processing — charge flow, refunds, webhook handling, error cases
# Subagent 3: notification system — delivery channels, retry logic, dedup, rate limits

# Build the project ontology from scan results:
facts add "a PaymentIntent is a Stripe object representing a single charge attempt" --section domain
facts add "a Webhook is an incoming HTTP POST from Stripe reporting a payment event" --section domain
facts add "a DeadLetter is a Webhook that exhausted all retry attempts" --section domain
facts add "a Session is a server-side auth record tied to a refresh token" --section domain
facts add "a PaymentIntent produces Webhooks on status changes" --section domain
facts add "failed Webhooks become DeadLetters after 3 retries" --section domain

# Classify existing facts by lifecycle stage (using domain vocabulary):

# This fact is true — code proves it
facts edit x1z --add-tag "implemented"

# This fact is precise but the code doesn't exist yet
facts edit a2b --add-tag "spec"

# This fact is vague ("supports payments") — needs refinement
facts edit c3d --add-tag "draft"

# An old fact about Python is no longer true — project migrated to Rust
facts remove p2q

# Found behavioral truths while reading code — add untagged (ground truth)
facts add "failed payment webhooks retry 3 times with exponential backoff, then dead-letter" \
  --section payments/webhooks
facts add "API rate limits to 100 req/min per key; exceeded requests get 429 with Retry-After header" \
  --section api/limits

# Verify everything
facts check

# Report: 6 domain facts added, 5 classified (@implemented: 3, @spec: 1, @draft: 1), 1 added, 1 removed
```
