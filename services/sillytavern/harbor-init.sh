#!/bin/sh
# Harbor SillyTavern backend pre-configuration
# Runs on every container start before SillyTavern starts.
# SILLYTAVERN_OLLAMA_URL   - set by compose.x.sillytavern.ollama.yml
# SILLYTAVERN_LLAMACPP_URL - set by compose.x.sillytavern.llamacpp.yml

export SETTINGS_FILE=/home/node/app/data/default-user/settings.json

if [ -n "$SILLYTAVERN_OLLAMA_URL" ] || [ -n "$SILLYTAVERN_LLAMACPP_URL" ]; then
    node - <<'HARBOR_INIT_EOF'
const fs = require('node:fs');
const path = require('node:path');

const ollamaUrl   = process.env.SILLYTAVERN_OLLAMA_URL   || '';
const llamacppUrl = process.env.SILLYTAVERN_LLAMACPP_URL || '';
const settingsPath = process.env.SETTINGS_FILE;

const serverUrls = {};

if (ollamaUrl) {
    serverUrls.ollama = ollamaUrl;
}

if (llamacppUrl) {
    serverUrls.llamacpp = llamacppUrl;
}

const primaryType = llamacppUrl ? 'llamacpp' : ollamaUrl ? 'ollama' : null;

if (fs.existsSync(settingsPath)) {
    // Returning user: patch existing settings in place
    const settings = JSON.parse(fs.readFileSync(settingsPath, 'utf8'));
    settings.main_api = 'textgenerationwebui';
    if (!settings.textgenerationwebui_settings) settings.textgenerationwebui_settings = {};
    settings.textgenerationwebui_settings.type        = primaryType;
    settings.textgenerationwebui_settings.server_urls = serverUrls;
    fs.writeFileSync(settingsPath, JSON.stringify(settings, null, 4), 'utf8');
    console.log('[Harbor] Patched existing settings.json — type=' + primaryType);
} else {
    // First-time user: create settings file with backend pre-configured
    const settingsDir = path.dirname(settingsPath);
    fs.mkdirSync(settingsDir, { recursive: true });
    const settings = {
        main_api: 'textgenerationwebui',
        textgenerationwebui_settings: {
            type: primaryType,
            server_urls: serverUrls,
        },
    };
    fs.writeFileSync(settingsPath, JSON.stringify(settings, null, 4), 'utf8');
    console.log('[Harbor] Created settings.json — type=' + primaryType);
}
HARBOR_INIT_EOF
fi

exec /home/node/app/docker-entrypoint.sh "$@"
