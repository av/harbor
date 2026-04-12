---
name: release
description: >
  Perform Harbor release procedures — version bumping, codegen, committing, pushing,
  and drafting GitHub releases. Use this skill when the user wants to release a new
  version of Harbor, bump the version number, create a release on GitHub, run the
  release codegen pipeline, or anything related to shipping a new Harbor version.
  Triggers on phrases like "release Harbor", "bump version", "new release",
  "ship a new version", or "prepare a release".
---

# Harbor Release Procedure

Releasing Harbor is a sequential pipeline: bump the version constant, run codegen
(which propagates the version across the monorepo and syncs docs to the wiki),
commit, push, research what changed, update the README News section, and open a
pre-filled GitHub release form.

## Pre-flight

Before starting, verify two things:

1. **Clean working tree** — `git status` should show no uncommitted changes.
   The codegen step touches many files; starting dirty makes the release commit noisy.
2. **Wiki repo exists** — `release.sh` pushes docs to `../harbor.wiki`. If the
   directory doesn't exist, the docs push will fail. Clone it first if missing:
   ```bash
   git clone https://github.com/av/harbor.wiki.git ../harbor.wiki
   ```

## Step 1 — Bump Version

Open `.scripts/seed.ts` and change the `VERSION` constant (line ~9):

```typescript
const VERSION = "X.Y.Z";
```

Bump **patch** by default (e.g. `0.4.2` → `0.4.3`). Bump minor or major only
when the user explicitly asks.

This constant is the single source of truth — the seed script propagates it to
`pyproject.toml`, `package.json`, `harbor.sh`, `app/package.json`,
`app/src-tauri/tauri.conf.json`, and `app/src-tauri/Cargo.toml`.

## Step 2 — Run Codegen

```bash
harbor dev release
```

This runs the release script (`.scripts/release.sh`), which:
- Seeds the version into all targets (`harbor dev seed`, `seed-cdi`, `seed-traefik`)
- Syncs docs to the wiki repo and pushes them

Wait for it to complete. Check the output for errors — especially the wiki push,
which can fail if there are merge conflicts in `../harbor.wiki`.

## Step 3 — Commit and Push

```bash
git add -A
git commit -m "chore: vX.Y.Z"
git push origin main
```

The commit message is always `chore: vX.Y.Z` — no variation.

## Step 4 — Research Changes

Identify what changed since the last release to write the release notes.

```bash
# Find the previous release tag
git tag --sort=-creatordate | head -5

# List commits since that tag
git log vPREV..HEAD --oneline

# If you need more detail on specific commits
git log vPREV..HEAD --stat
```

Classify each commit:
- **New services**: look for `feat: <service-name>` commits, or new `services/compose.<name>.yml` files
- **Notable changes**: `feat:` commits that aren't new services
- **Bugfixes**: `fix:` commits
- **Improvements**: `chore:` commits worth mentioning (not all are — skip routine ones)

For merged PRs, check:
```bash
git log vPREV..HEAD --oneline --merges
```

## Step 5 — Update README News Section

Update the `## News` list in `README.md` to include the new release. The list
lives between the screenshot image and the `## Documentation` heading.

1. Add a new bullet at the **top** of the list for `vX.Y.Z` with a short
   highlights summary (one sentence, 2-3 key changes from Step 4).
2. Remove the **oldest bullet** (bottom) so the list always shows exactly 7 releases.

The bullet format is:

```
- **vX.Y.Z** - Short highlights sentence
```

## Step 6 — Open GitHub Release Form

Construct the URL and open it with `xdg-open` (not an internal browser).

Base: `https://github.com/av/harbor/releases/new`

Query parameters:

| Param | Value |
|-------|-------|
| `tag` | `vX.Y.Z` |
| `target` | `main` |
| `title` | `vX.Y.Z` if no new services, otherwise `vX.Y.Z - Service1, Service2` |
| `prerelease` | `false` |
| `body` | Release notes (see template below) |

The `body` value must be URL-encoded. Use Python or similar to build the URL:

```bash
python3 -c "
import urllib.parse
body = '''RELEASE_NOTES_HERE'''
params = urllib.parse.urlencode({
    'tag': 'vX.Y.Z',
    'target': 'main',
    'title': 'vX.Y.Z',
    'body': body,
    'prerelease': 'false'
})
print(f'https://github.com/av/harbor/releases/new?{params}')
"
```

Then open the printed URL with `xdg-open`.

### Release Notes Template

```markdown
### [ServiceName](https://github.com/av/harbor/wiki/2.x.x-Service-ServiceName)

<SCREENSHOT_PLACEHOLDER>

One sentence description of the service.

\`\`\`bash
harbor up servicename
\`\`\`

### Misc

- One short sentence per notable change.
- One short sentence per notable bugfix.
- One short sentence per notable improvement.

**Full Changelog**: https://github.com/av/harbor/compare/vPREV...vX.Y.Z
```

If no new services were added, omit the service sections entirely — just use the
Misc section and the Full Changelog link.

The wiki link format for services follows the pattern `2.x.x-Category-ServiceName`
where the category and numbering match the docs file (e.g. `2.3.0-Satellite-SearXNG`).
Check the `docs/` directory for the exact page name.
