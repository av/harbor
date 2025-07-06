#!/bin/bash

HOME=$(harbor home)
SOURCE="${HOME}/boost/src/custom_modules/artifacts/nbs.html"
OUTPUT="${HOME}/boost/src/custom_modules/artifacts/nbs_mini.html"
CMD="npx html-minifier-terser --collapse-whitespace --remove-comments --minify-css true --minify-js true $SOURCE -o $OUTPUT"

watchexec -v -w "$SOURCE" --timings --no-process-group -r -e pug,ts --project-origin $HOME --no-project-ignore -- "$CMD"