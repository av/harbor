---
name: facts
description: >
  Manage .facts files — atomic, validatable truth statements about a project.
  Install, check, list, add, edit, remove, and lint facts via the CLI.
  ALWAYS read this skill when the user mentions facts in any capacity.
---

# facts

A CLI for fact-driven development. You use it to specify what must be true about a project, then validate that reality matches.

Project: https://github.com/av/facts

## Installing

If `facts` is not installed, install it with one of:

```bash
curl -fsSL https://raw.githubusercontent.com/av/facts/main/install.sh | sh
```

```bash
npm install -g @avcodes/facts
```

```bash
pipx install facts-cli
```

Verify with `facts --version`. The command is always `facts` — never `npx facts`.

## Core idea

A `.facts` file is a flat list of atomic truth statements about a project. Each fact can optionally have a shell command that verifies it. The fact sheet serves as both specification (what should be true) and documentation (what is true) — the difference is just which direction you're working from.

```
- the API returns JSON
- label: project builds
  command: cargo build
- label: tests pass
  command: cargo test
  tags: [ci, core]
```

That's the entire format. Plain strings for simple facts, mappings when you need a command, tags, or explicit ID. Allowed mapping keys: `id`, `label`, `command`, `tags` — nothing else.

## Essential commands

**Recommended short aliases** (all extra arguments are passed through):
- `ll` = `list --light` — the most common "skim" view (markdown headings + dim IDs)
- `ls` = `list`
- `rm` = `remove`
- `at <id> <tag>` = `edit <id> --add-tag <tag>` (supports multiple IDs and `--label` / `--new-id` etc. after the tag)
- `rt <id> <tag>` = `edit <id> --remove-tag <tag>`

These are the highest-ROI shortcuts for daily and agent use.

**See everything:**
```
facts ll
facts ll --tags "not implemented"
facts ll --has-command
facts list --light                      # or the alias: facts ll
```

**Validate:**
```
facts check
facts check --tags "ci"
```
`check` is your primary feedback loop. It lints the files first (aborting on structural errors), then runs every command-fact and reports pass/fail/manual. Run it often. Exit 0 means all command-facts pass; manual facts don't affect the exit code.

**Manual facts (`?` in output) are your responsibility.** They have no command — you verify them by reading the relevant code. For each `?` fact: read what it claims, check the code, then report PASS or FAIL with a one-line reason. Reporting "N manual" without checking each one is not acceptable — those facts exist because they describe behavior that matters.

**Add facts:**
```
facts add "users can sign up" --section features/auth
facts add "signup returns 201" --command "curl -s -o /dev/null -w '%{http_code}' localhost:3000/signup | grep 201" --section features/auth
```

**Edit / tag facts (lifecycle transitions):**
```
facts at <id> "implemented"          # most common: quick add tag
facts rt <id> "spec"                 # quick remove tag
facts at <id> "spec" --new-id xyz    # extra flags still work
facts edit <id> --label "corrected statement"
facts edit <id> --command "new check command"
```
Prefer `at`/`rt` (or the long `--add-tag` / `--remove-tag` forms) over the full `--tags` replacement. The latter replaces all tags silently.

**Remove facts:**
```
facts rm <id>     # or the long form: facts remove <id>
```

**Scaffold a new project:**
```
facts init
```

Run `facts <command> --help` for the full flag reference.

## How facts work

**Files:** `.facts` is the default. Additional sheets use semantic names (`cli.facts`, `api.facts`). All `*.facts` files in the project root are discovered automatically.

**Sections:** Markdown headings (`#`, `##`, etc.) create hierarchical sections addressable by path (e.g. `cli/subcommands`). Sections are created when you add to them and removed when their last fact is deleted.

**Tags:** `@word` tokens for filtering. Inline for plain strings (`- some fact @mvp`), `tags:` key for mappings. Stripped from the label before display and ID hashing. Filter with boolean expressions: `--tags "mvp and not blocked"`.

**Lifecycle tags:** Three well-known tags drive the agent workflow:
- `@draft` — rough idea, needs refinement and atomization
- `@spec` — precise and actionable, ready to implement
- `@implemented` — true and backed by code
- Untagged facts are ground truth — verified against the codebase

The lifecycle flows `@draft → @spec → @implemented`. Each companion skill owns one transition.

**IDs:** Every fact gets a short ID (3+ chars) derived from its label hash. Stable as long as the label doesn't change. Use `--id` or `--new-id` to override.

**Validation:** Commands run via `$SHELL` (fallback `sh`) in the project root. Exit 0 = fact holds. Write commands that are fast and idempotent — they run on every check.

## Writing good facts

Facts should describe what the project **does** — its behaviors, features, and contracts — not what files it has or what libraries it uses. The test: if an agent reimplemented this project using only the fact sheet, would the result behave correctly?

- **Behavioral** — describe what happens from the user's perspective ("expired tokens are rejected with 401") not what exists in the code ("there is an auth module")
- **Atomic** — one truth per fact, independently verifiable
- **Declarative** — state what is true, not what to do ("uses PostgreSQL" not "set up PostgreSQL")
- **Stable** — shouldn't change with every commit ("tests pass" not "there are 47 tests")
- **Falsifiable** — you could imagine a broken implementation where this fact would not hold

Structural facts (dependencies, file layout) are supporting detail, not the main content. A fact sheet full of "uses X library" and "has Y directory" tells an agent nothing about how the project actually works.

Good validation commands are fast, idempotent, and test one thing. Prefer `test -f`, `grep -q`, and short script checks over running full builds.

## Domain vocabulary

The `## domain` section in the main `.facts` file defines the project's key entities and their relationships. These are facts too — atomic truth statements — but they describe the conceptual model rather than specific behaviors.

Entity facts name and define a concept — the common pattern is `a <Name> is <definition>`.
Relation facts state how entities connect. Use the defined entity names in natural declarative statements — there is no rigid grammar, but the connection should be specific.

```
## domain
- a FactSheet is a parsed *.facts file containing sections and facts
- a Section is a heading-delimited group of facts, nestable via heading depth
- a Fact is an atomic truth statement: a label, optional command, optional tags
- a FactSheet contains a preamble and nested Sections
- check validates command-bearing Facts by running them in the project root
- Tags filter Facts via boolean expressions
```

Use these names consistently across the fact sheet. The domain section lives in the main `.facts` file. It is built by `facts-discover`, refined by `facts-refine`, and extended by `facts-implement` when new concepts emerge during implementation.

## Agent workflows

**Start of work — always do this first:**
```
facts ll                                # read the full spec (skim view)
facts check                             # see what holds and what doesn't
```
Use the fact sheet to orient before writing code. It is the source of truth for what the project should look like and what is already validated.

**Define the spec (most common user intent):**
When the user says "work on facts", "add facts", or "define the spec", they want to collaboratively define what should be true — not audit what already is.
```
facts add "users can sign up" --section features/auth --tags "draft"
facts add "signup returns 201" --command "curl -s ..." --section features/auth --tags "spec"
```
- Discuss with the user what the project should look like
- Add rough ideas as `@draft` — they'll be refined into precise specs later
- Add precise, actionable facts as `@spec` — they're ready to implement
- Do NOT remove `@draft` or `@spec` facts — they represent intended future work
- Do NOT run `facts-discover` unless the user explicitly asks to sync with reality

**Track lifecycle progress:**
```
facts ll --tags "draft"                 # rough ideas to refine (ll = list --light)
facts ll --tags "spec"                  # ready to implement
facts ll --tags "implemented"           # done
facts ll --tags "not implemented"       # all remaining work
facts check                             # verify
```

**Maintain accuracy during coding work:**
When you add a feature, add corresponding facts. When you fix a bug, verify related facts still hold. When you remove code, remove obsolete facts.
```
facts check                             # find failing facts
facts at <id> "implemented"             # or the long form: facts edit <id> --add-tag "implemented"
facts rm <id>                           # remove obsolete facts
facts add "new truth" --section foo     # add discovered truths
```

## Companion skills

Each skill owns one lifecycle transition:

- **facts-discover** — scan the codebase and classify every fact by lifecycle stage (`@draft`, `@spec`, `@implemented`). Use to triage or bootstrap.
- **facts-refine** — pick up `@draft` facts and refine them into precise `@spec` facts with the user. Use when drafts need sharpening.
- **facts-implement** — pick up `@spec` facts and implement them in code, then tag `@implemented`. Use when specs are ready to build.
