#!/usr/bin/env bash

set -eo pipefail

npx html-minifier-terser --collapse-whitespace --remove-comments --minify-css true --minify-js true ./boost/src/custom_modules/artifacts/tokens.html -o ./boost/src/custom_modules/artifacts/tokens_mini.html
