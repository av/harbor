#!/usr/bin/env bash

set -eo pipefail

echo "Seeding..."
harbor dev seed

echo "Moving docs..."
harbor dev docs

# echo "NPM Publish..."
npm publish --access public

# echo "PyPi Publish..."
poetry env use system
poetry build -v
poetry publish -v