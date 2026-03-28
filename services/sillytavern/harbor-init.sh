#!/bin/sh
# Harbor SillyTavern backend pre-configuration
# Runs on every container start before SillyTavern starts.
# SILLYTAVERN_OLLAMA_URL   - set by compose.x.sillytavern.ollama.yml
# SILLYTAVERN_LLAMACPP_URL - set by compose.x.sillytavern.llamacpp.yml

export SETTINGS_FILE=/home/node/app/data/default-user/settings.json
export SEED_FILE=/home/node/app/default/content/settings.json

if [ -n "$SILLYTAVERN_OLLAMA_URL" ] || [ -n "$SILLYTAVERN_LLAMACPP_URL" ]; then
    node - <<'HARBOR_INIT_EOF'
const fs = require('node:fs');

const ollamaUrl   = process.env.SILLYTAVERN_OLLAMA_URL   || '';
const llamacppUrl = process.env.SILLYTAVERN_LLAMACPP_URL || '';
const settingsPath = process.env.SETTINGS_FILE;
const seedPath     = process.env.SEED_FILE;

const serverUrls = {};

if (ollamaUrl) {
    serverUrls.ollama = ollamaUrl;
}

if (llamacppUrl) {
    serverUrls.llamacpp = llamacppUrl;
}

const primaryType = llamacppUrl ? 'llamacpp' : ollamaUrl ? 'ollama' : null;

function patchSettings(filePath) {
    const settings = JSON.parse(fs.readFileSync(filePath, 'utf8'));
    settings.main_api = 'textgenerationwebui';
    if (!settings.textgenerationwebui_settings) settings.textgenerationwebui_settings = {};
    settings.textgenerationwebui_settings.type        = primaryType;
    settings.textgenerationwebui_settings.server_urls = serverUrls;
    fs.writeFileSync(filePath, JSON.stringify(settings, null, 4), 'utf8');
    return settings;
}

// Always patch the seed file so first-time users get correct defaults
patchSettings(seedPath);
console.log('[Harbor] Patched seed settings.json — type=' + primaryType);

// If the live settings file exists (returning user), patch it too
if (fs.existsSync(settingsPath)) {
    patchSettings(settingsPath);
    console.log('[Harbor] Patched existing settings.json — type=' + primaryType);
}
HARBOR_INIT_EOF
fi

exec /home/node/app/docker-entrypoint.sh "$@"
