#!/usr/bin/env bash

set -eo pipefail

echo "Seeding..."
harbor dev seed
harbor dev seed-cdi
harbor dev seed-traefik

echo "Moving docs..."
harbor dev docs

# cd to wiki and push the docs
cd ../harbor.wiki
git add .
git commit -m "chore: docs"
git push origin master
cd ../harbor

# echo "NPM Publish..."
# npm publish --access public

# # # echo "PyPi Publish..."
# poetry env use system
# poetry build -v
# poetry publish -v