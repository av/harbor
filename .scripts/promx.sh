#!/bin/bash

# watchexec
# https://github.com/watchexec/watchexec/blob/main/doc/packages.md
# 1. `cargo install cargo-binstall`
# 2. `cargo binstall watchexec-cli`

HOME=$(harbor home)
ARTIFACT_DIR="$HOME/boost/src/custom_modules/artifacts/promx"
ARTIFACT_DIST="$ARTIFACT_DIR/dist"
CMD="cd $ARTIFACT_DIR; parcel build --no-optimize index.pug; cd $HOME; deno -A ./.scripts/inliner.ts $ARTIFACT_DIST index.html"

watchexec -v -w "$ARTIFACT_DIR" --timings --no-process-group -r -e pug,ts,css --project-origin $HOME --no-project-ignore -- "$CMD"
