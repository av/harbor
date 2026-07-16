#!/usr/bin/env bash

set -eo pipefail

echo "Seeding..."
harbor dev seed
harbor dev seed-cdi
harbor dev seed-traefik
harbor dev lint

# Seeding bumps app/src-tauri/Cargo.toml; refresh the lockfile so it doesn't go stale
if command -v cargo >/dev/null 2>&1; then
  echo "Syncing app/src-tauri/Cargo.lock..."
  (cd app/src-tauri && cargo update --workspace)
else
  echo "WARNING: cargo not found — app/src-tauri/Cargo.lock NOT synced with the bumped Cargo.toml version. Run 'cargo update --workspace' in app/src-tauri manually." >&2
fi

echo "Moving docs..."
harbor dev docs

# cd to wiki and push the docs
cd ../harbor.wiki
git add . || true
# Commit only if there are changes
if git diff-index --quiet HEAD --; then
  echo "No docs changes to commit"
else
  git commit -m "chore: docs"
  git push origin master || true
fi
cd ../harbor

# echo "NPM Publish..."
# npm publish --access public

# # # echo "PyPi Publish..."
# poetry env use system
# poetry build -v
# poetry publish -v