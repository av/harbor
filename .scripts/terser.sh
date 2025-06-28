#!/usr/bin/env bash

set -eo pipefail

# npx html-minifier-terser --collapse-whitespace --remove-comments --minify-css true --minify-js true ./boost/src/custom_modules/artifacts/tokens.html -o ./boost/src/custom_modules/artifacts/tokens_mini.html
# npx html-minifier-terser --collapse-whitespace --remove-comments --minify-css true --minify-js true ./boost/src/custom_modules/artifacts/graph.html -o ./boost/src/custom_modules/artifacts/graph_mini.html
# npx html-minifier-terser --collapse-whitespace --remove-comments --minify-css true --minify-js true ./boost/src/custom_modules/artifacts/dnd.html -o ./boost/src/custom_modules/artifacts/dnd_mini.html
# npx html-minifier-terser --collapse-whitespace --remove-comments --minify-css true --minify-js true ./boost/src/custom_modules/artifacts/dot.html -o ./boost/src/custom_modules/artifacts/dot_mini.html
# npx html-minifier-terser --collapse-whitespace --remove-comments --minify-css true --minify-js true ./boost/src/custom_modules/artifacts/ponder.html -o ./boost/src/custom_modules/artifacts/ponder_mini.html
npx html-minifier-terser --collapse-whitespace --remove-comments --minify-css true --minify-js true ./boost/src/custom_modules/artifacts/fluid/dist/index_built.html -o ./boost/src/custom_modules/artifacts/fluid_mini.html
npx html-minifier-terser --collapse-whitespace --remove-comments --minify-css true --minify-js true ./boost/src/custom_modules/artifacts/promx/dist/index_built.html -o ./boost/src/custom_modules/artifacts/promx_mini.html
