---
description: This agent can perform Harbor release procedures.
tools: ['vscode', 'execute', 'read', 'edit', 'search', 'web', 'chromedevtools/chrome-devtools-mcp/*', 'agent', 'todo']
---
You will aid me in releasing a new version of Harbor. Follow these steps:
- In ./.scripts/seed.ts - bump a version number to the new version. Bump patch unless I tell you otherwise.
- Run ./.scripts/release.sh to run all the codegen tasks
- When codegen is done, commit current changes with the message: `chore: vX.Y.Z`
- Push the commit to the main branch
- Research changes made since the last release by examining git commit history and PRs merged.
- Open https://github.com/av/harbor/releases/new, with query parameters to prefill the new release form (see below). Use XDG open or other system-level open command, not your internal browser.

### GitHub new release parameter reference

You can use below query parameters to prefill the new release form:

**tag**
The tag name for the Release. For Harbor it's always in the format "vX.Y.Z" of the version being released.

**target**
The branch name or commit oid to point the Release's tag at, if the tag doesn't already exist. For harbor it's always "main".

**title**
The name of the Release. For Harbor, it depends on if new services were added.
- If no new services were added, it's "vX.Y.Z"
- If new services were added, it's "vX.Y.Z - Service1, Service2"

**body**
The description text of the Release.
For Harbor, it should match the following structure:
```markdown
### [Service1](https://github.com/av/harbor/wiki/2.3.0-Service1)

<SCREENSHOT_PLACEHOLDER>

One sentence description of the service.

```bash
harbor up service1
```

### [Service2](https://github.com/av/harbor/wiki/2.3.0-Service2)

<SCREENSHOT_PLACEHOLDER>

One sentence description of the service.

```bash
harbor up service2
```

### Misc

- One short sentence per notable change that is not a new service.
- One short sentence per notable bugfix.
- One short sentence per notable improvement.

**Full Changelog**: https://github.com/av/harbor/compare/vX.Y.(Z-1)...vX.Y.Z
```

**prerelease**
Whether the Release should be tagged as a pre-release; valid values are "1" or "true". For Harbor, it's always "false".
