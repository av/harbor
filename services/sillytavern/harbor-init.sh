#!/bin/sh
# Harbor SillyTavern backend pre-configuration
# Runs on every container start before SillyTavern starts.
# SILLYTAVERN_OLLAMA_URL   - set by compose.x.sillytavern.ollama.yml
# SILLYTAVERN_LLAMACPP_URL - set by compose.x.sillytavern.llamacpp.yml
# SILLYTAVERN_DMR_URL      - set by compose.x.sillytavern.dmr.yml
# SILLYTAVERN_MLX_URL      - set by compose.x.sillytavern.mlx.yml
# SILLYTAVERN_OMLX_URL     - set by compose.x.sillytavern.omlx.yml

export SETTINGS_FILE=/home/node/app/data/default-user/settings.json
export SEED_FILE=/home/node/app/default/content/settings.json

if [ -n "$SILLYTAVERN_OLLAMA_URL" ] || [ -n "$SILLYTAVERN_LLAMACPP_URL" ] || [ -n "$SILLYTAVERN_DMR_URL" ] || [ -n "$SILLYTAVERN_MLX_URL" ] || [ -n "$SILLYTAVERN_OMLX_URL" ]; then
    node - <<'HARBOR_INIT_EOF'
const fs = require('node:fs');

const ollamaUrl   = process.env.SILLYTAVERN_OLLAMA_URL   || '';
const llamacppUrl = process.env.SILLYTAVERN_LLAMACPP_URL || '';
// DMR, MLX and OMLX are OpenAI-compatible — mapped to SillyTavern's 'generic' type
const genericUrl  = process.env.SILLYTAVERN_OMLX_URL
    || process.env.SILLYTAVERN_MLX_URL
    || process.env.SILLYTAVERN_DMR_URL
    || '';
const settingsPath = process.env.SETTINGS_FILE;
const seedPath     = process.env.SEED_FILE;

const serverUrls = {};

if (ollamaUrl) {
    serverUrls.ollama = ollamaUrl;
}

if (llamacppUrl) {
    serverUrls.llamacpp = llamacppUrl;
}

if (genericUrl) {
    serverUrls.generic = genericUrl;
}

const primaryType = genericUrl ? 'generic' : llamacppUrl ? 'llamacpp' : ollamaUrl ? 'ollama' : null;

function patchSettings(filePath) {
    const settings = JSON.parse(fs.readFileSync(filePath, 'utf8'));
    settings.main_api = 'textgenerationwebui';
    if (!settings.textgenerationwebui_settings) settings.textgenerationwebui_settings = {};
    settings.textgenerationwebui_settings.type        = primaryType;
    const existingUrls = settings.textgenerationwebui_settings.server_urls;
    const isObject = typeof existingUrls === 'object' && existingUrls !== null && !Array.isArray(existingUrls);
    settings.textgenerationwebui_settings.server_urls = Object.assign(
        isObject ? existingUrls : {},
        serverUrls
    );
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
