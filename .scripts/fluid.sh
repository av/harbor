#!/bin/bash

# watchexec
# https://github.com/watchexec/watchexec/blob/main/doc/packages.md
# 1. `cargo install cargo-binstall`
# 2. `cargo binstall watchexec-cli`

HOME=$(harbor home)
ARTIFACT_DIR="$HOME/boost/src/custom_modules/artifacts/fluid"
ARTIFACT_SRC="$ARTIFACT_DIR/index.pug"
CMD="cd $ARTIFACT_DIR; parcel build --no-optimize index.pug; cd $HOME; deno -A ./.scripts/inline-fluid.ts"

watchexec -v -w "$ARTIFACT_DIR" --timings --no-process-group -r -e pug,ts --project-origin $HOME --no-project-ignore -- "$CMD"
# npx parcel build --no-optimize "$ARTIFACT_SRC"
# deno -A ./.scripts/inline-fluid.ts