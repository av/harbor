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

**See everything:**
```
facts list
facts list --tags "not implemented"
facts list --has-command
```

**Validate:**
```
facts check
facts check --tags "ci"
```
`check` is your primary feedback loop. It lints the files first (aborting on structural errors), then runs every command-fact and reports pass/fail/manual. Run it often. Exit 0 means all command-facts pass; manual facts don't affect the exit code.

**Add facts:**
```
facts add "users can sign up" --section features/auth
facts add "signup returns 201" --command "curl -s -o /dev/null -w '%{http_code}' localhost:3000/signup | grep 201" --section features/auth
```

**Edit facts:**
```
facts edit <id> --add-tag "implemented"
facts edit <id> --remove-tag "blocked"
facts edit <id> --label "corrected statement"
facts edit <id> --command "new check command"
```
Prefer `--add-tag` / `--remove-tag` over `--tags`. The latter replaces all tags silently — use it only when you intend a full replacement.

**Remove facts:**
```
facts remove <id>
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

- **Atomic** — one truth per fact, independently verifiable
- **Declarative** — state what is true, not what to do ("uses PostgreSQL" not "set up PostgreSQL")
- **Stable** — shouldn't change with every commit ("tests pass" not "there are 47 tests")
- **Verifiable** — add a command when a simple check exists; manual facts are fine for things that need judgment

Good validation commands are fast, idempotent, and test one thing. Prefer `test -f`, `grep -q`, and short script checks over running full builds.

## Agent workflows

**Start of work — always do this first:**
```
facts list                              # read the full spec
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
facts list --tags "draft"               # rough ideas to refine
facts list --tags "spec"                # ready to implement
facts list --tags "implemented"         # done
facts list --tags "not implemented"     # all remaining work
facts check                             # verify
```

**Maintain accuracy during coding work:**
When you add a feature, add corresponding facts. When you fix a bug, verify related facts still hold. When you remove code, remove obsolete facts.
```
facts check                             # find failing facts
facts edit <id> --label "corrected"     # fix inaccurate facts
facts remove <id>                       # remove obsolete facts
facts add "new truth" --section foo     # add discovered truths
```

## Companion skills

Each skill owns one lifecycle transition:

- **facts-discover** — scan the codebase and classify every fact by lifecycle stage (`@draft`, `@spec`, `@implemented`). Use to triage or bootstrap.
- **facts-refine** — pick up `@draft` facts and refine them into precise `@spec` facts with the user. Use when drafts need sharpening.
- **facts-implement** — pick up `@spec` facts and implement them in code, then tag `@implemented`. Use when specs are ready to build.
