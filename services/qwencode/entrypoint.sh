#!/bin/sh
set -eu

if [ -z "${QWEN_SERVER_TOKEN:-}" ]; then
  unset QWEN_SERVER_TOKEN
fi

if [ "${HARBOR_QWENCODE_OLLAMA_ENABLED:-}" = "true" ]; then
  mkdir -p /root/.qwen
  node <<'NODE'
const fs = require('fs');
const path = '/root/.qwen/settings.json';
const model = process.env.HARBOR_QWENCODE_OLLAMA_MODEL;
const baseUrl = process.env.OPENAI_BASE_URL;
let settings = {};

try {
  settings = JSON.parse(fs.readFileSync(path, 'utf8'));
} catch (error) {
  if (error.code !== 'ENOENT') throw error;
}

settings.modelProviders ??= {};
settings.modelProviders.openai ??= [];
if (!settings.modelProviders.openai.some((provider) => provider.id === model)) {
  settings.modelProviders.openai.push({
    id: model,
    name: `Harbor Ollama (${model})`,
    baseUrl,
    envKey: 'OPENAI_API_KEY',
  });
}
settings.security ??= {};
settings.security.auth ??= {};
settings.security.auth.selectedType ??= 'openai';
settings.model ??= {};
settings.model.name ??= model;

const nextPath = `${path}.harbor-tmp`;
fs.writeFileSync(nextPath, `${JSON.stringify(settings, null, 2)}\n`, { mode: 0o600 });
fs.renameSync(nextPath, path);
NODE
fi

exec "$@"
