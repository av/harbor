#!/bin/sh
set -eu

if [ "$(id -u)" = "0" ]; then
  chown -R open-design:open-design /app/.od
fi

node <<'NODE'
const fs = require('node:fs');
const path = '/app/apps/web/out/index.html';
const markerStart = '<script id="harbor-open-design-defaults">';
const markerEnd = '</script>';

(async () => {
  const protocol = process.env.HARBOR_OPEN_DESIGN_DEFAULT_API_PROTOCOL || '';
  const baseUrl = process.env.HARBOR_OPEN_DESIGN_DEFAULT_BASE_URL || '';
  const apiKey = process.env.HARBOR_OPEN_DESIGN_DEFAULT_API_KEY || '';
  let model = process.env.HARBOR_OPEN_DESIGN_DEFAULT_MODEL || '';
  const providerBaseUrl = process.env.HARBOR_OPEN_DESIGN_DEFAULT_PROVIDER_BASE_URL || baseUrl;
  const force = String(process.env.HARBOR_OPEN_DESIGN_FORCE_DEFAULTS || '').toLowerCase() === 'true';

async function resolveModel() {
  if (model !== 'auto' || !baseUrl) return;
  try {
    const response = await fetch(`${baseUrl.replace(/\/+$/, '')}/models`);
    if (!response.ok) return;
    const catalog = await response.json();
    const first = Array.isArray(catalog?.data) ? catalog.data[0]?.id : '';
    if (typeof first === 'string' && first.trim()) {
      model = first.trim();
    }
  } catch {
    // Keep the configured value; the UI will surface connection issues.
  }
}

  await resolveModel();

  if (protocol && baseUrl && model && fs.existsSync(path)) {
    const payload = {
      protocol,
      baseUrl,
      apiKey,
      model,
      providerBaseUrl,
      force,
    };
    const script = `${markerStart}(function(){try{var d=${JSON.stringify(payload)};var k='open-design:config';var raw=localStorage.getItem(k);if(raw&&!d.force)return;var cfg=raw?JSON.parse(raw):{};var entry={apiKey:d.apiKey,baseUrl:d.baseUrl,model:d.model,apiProviderBaseUrl:d.providerBaseUrl||null};cfg=Object.assign({},cfg,{mode:'api',apiProtocol:d.protocol,apiKey:d.apiKey,baseUrl:d.baseUrl,model:d.model,apiProviderBaseUrl:d.providerBaseUrl||null,apiProtocolConfigs:Object.assign({},cfg.apiProtocolConfigs||{},((o={})=>{o[d.protocol]=entry;return o;})()),configMigrationVersion:1});localStorage.setItem(k,JSON.stringify(cfg));}catch(e){console.warn('Harbor Open Design defaults failed',e);}}());${markerEnd}`;
    let html = fs.readFileSync(path, 'utf8');
    const start = html.indexOf(markerStart);
    if (start >= 0) {
      const end = html.indexOf(markerEnd, start);
      if (end >= 0) {
        html = `${html.slice(0, start)}${script}${html.slice(end + markerEnd.length)}`;
      }
    } else {
      html = html.replace('</head>', `${script}</head>`);
    }
    fs.writeFileSync(path, html);
  }
})();
NODE

if [ "$(id -u)" = "0" ]; then
  exec su open-design -s /bin/sh -c 'exec node apps/daemon/dist/cli.js --no-open'
fi

exec node apps/daemon/dist/cli.js --no-open
