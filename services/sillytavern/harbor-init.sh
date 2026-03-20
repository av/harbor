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
let primaryType  = null;

if (ollamaUrl)   { serverUrls['ollama']   = ollamaUrl;   primaryType = primaryType || 'ollama';   }
if (llamacppUrl) { serverUrls['llamacpp'] = llamacppUrl; primaryType = primaryType || 'llamacpp'; }

// Patch the live settings file if it already exists (returning user)
if (fs.existsSync(settingsPath)) {
    const settings = JSON.parse(fs.readFileSync(settingsPath, 'utf8'));
    settings.main_api = 'textgenerationwebui';
    if (!settings.textgenerationwebui_settings) settings.textgenerationwebui_settings = {};
    settings.textgenerationwebui_settings.type        = primaryType;
    settings.textgenerationwebui_settings.server_urls = serverUrls;
    fs.writeFileSync(settingsPath, JSON.stringify(settings, null, 4), 'utf8');
    console.log('[Harbor] Patched existing settings.json — type=' + primaryType);
} else {
    console.log('[Harbor] No existing settings.json — will be seeded from defaults.');
}

// Update the seed file for fresh installs or volume resets
const seed = {
    main_api: 'textgenerationwebui',
    textgenerationwebui_settings: {
        type: primaryType,
        server_urls: serverUrls,
    },
};
fs.writeFileSync(seedPath, JSON.stringify(seed, null, 4), 'utf8');
console.log('[Harbor] Wrote seed settings.json — type=' + primaryType);
HARBOR_INIT_EOF
fi

exec /home/node/app/docker-entrypoint.sh "$@"
