import type { ComposeContext, ComposeObject } from '../routines/composeTypes';
import { getAllActiveBackends, addBackendDependency, type DetectedBackend } from '../routines/backendIntegration';

/**
 * Generates an inline bash script that:
 * 1. Waits for each backend to become available
 * 2. Queries /v1/models to discover available models
 * 3. Writes an opencode.json config with discovered providers
 * 4. Executes opencode with original arguments
 *
 * Note: All $ must be escaped as $$ for Docker Compose interpolation.
 */
function generateHarborCliInitScript(): string {
  return `
if [ -x /harbor/harbor_cli_init.sh ]; then
  /harbor/harbor_cli_init.sh || echo "harbor-cli init failed; continuing without harbor CLI"
fi
`.trim();
}

function generateDiscoveryScript(backends: DetectedBackend[]): string {
  const backendList = backends.map(b => `${b.service}=${b.info.url}`).join(' ');

  // Note: Using string concatenation for bash syntax that conflicts with JS template literals
  const configDirDefault = '$$' + '{OPENCODE_CONFIG_DIR:-/root/.config/opencode}';
  const backendNameExtract = '$$' + '{backend%%=*}';
  const backendUrlExtract = '$$' + '{backend#*=}';

  return `
set -e
${generateHarborCliInitScript()}
CONFIG_DIR="${configDirDefault}"
mkdir -p "$$CONFIG_DIR"
CONFIG_FILE="$$CONFIG_DIR/opencode.json"

# Wait for backend with retries
wait_for() {
  url="$$1"
  attempt=0
  while [ $$attempt -lt 30 ]; do
    curl -sf "$$url/v1/models" > /dev/null 2>&1 && return 0
    sleep 1
    attempt=$$((attempt + 1))
  done
  return 1
}

discover() {
  url="$$1"
  key="$$2"
  if [ -n "$$key" ]; then
    curl -sf -H "Authorization: Bearer $$key" "$$url/v1/models" 2>/dev/null
  else
    curl -sf "$$url/v1/models" 2>/dev/null
  fi
}

# Per-backend API key resolver. Cross-integration files (e.g. unsloth-studio)
# drop a sidecar key file at /run/<backend>-auth/api_key.txt — read it at
# runtime so the discovery script picks up freshly-minted bootstrap keys
# without a second pass. Defaults to "sk-harbor" for backends that don't
# validate auth (ollama, llamacpp).
resolve_key() {
  name="$$1"
  key_file="/run/$$name-auth/api_key.txt"
  if [ -r "$$key_file" ]; then
    k=$$(tr -d '\\n' < "$$key_file")
    if [ -n "$$k" ]; then
      printf '%s' "$$k"
      return 0
    fi
  fi
  printf '%s' "sk-harbor"
}

echo '{"$$schema":"https://opencode.ai/config.json","provider":{' > "$$CONFIG_FILE"
first=true

for backend in ${backendList}; do
  name="${backendNameExtract}"
  url="${backendUrlExtract}"
  api_key=$$(resolve_key "$$name")

  echo "Waiting for $$name at $$url..."
  wait_for "$$url" || { echo "Backend $$name not available after 30s, skipping"; continue; }

  echo "Discovering models from $$name..."
  models=$$(discover "$$url" "$$api_key") || { echo "Failed to get models from $$name"; continue; }

  model_ids=$$(echo "$$models" | grep -o '"id":"[^"]*"' | cut -d'"' -f4)
  [ -z "$$model_ids" ] && { echo "No models found for $$name"; continue; }

  $$first || echo ',' >> "$$CONFIG_FILE"
  first=false

  cat >> "$$CONFIG_FILE" << PROVIDER
"harbor-$$name":{"npm":"@ai-sdk/openai-compatible","name":"$$name (Harbor)","options":{"baseURL":"$$url/v1","apiKey":"$$api_key"},"models":{
PROVIDER

  mfirst=true
  for mid in $$model_ids; do
    $$mfirst || echo ',' >> "$$CONFIG_FILE"
    mfirst=false
    echo "\\"$$mid\\":{\\"name\\":\\"$$mid\\",\\"attachment\\":true,\\"tool_call\\":true,\\"limit\\":{\\"context\\":128000,\\"output\\":8192}}" >> "$$CONFIG_FILE"
  done

  echo '}}' >> "$$CONFIG_FILE"
  echo "Discovered models from $$name: $$(echo "$$model_ids" | tr '\\n' ' ')"
done

echo '}}' >> "$$CONFIG_FILE"
echo "Generated config at $$CONFIG_FILE"

exec opencode serve --hostname=0.0.0.0 --port=4096
`.trim();
}

export default async function apply(ctx: ComposeContext): Promise<ComposeObject> {
  const { compose, env, services } = ctx;

  if (!compose.services?.opencode) {
    return compose;
  }

  // Handle workspace mounting
  const workspacesStr = await env.getValue('opencode.workspaces');
  if (workspacesStr) {
    const workspaces = workspacesStr
      .split(';')
      .map(w => w.trim())
      .filter(w => w.length > 0);

    if (workspaces.length > 0) {
      if (!compose.services.opencode.volumes) {
        compose.services.opencode.volumes = [];
      }

      if (!Array.isArray(compose.services.opencode.volumes)) {
        compose.services.opencode.volumes = [];
      }

      const existingVolumes = new Set(compose.services.opencode.volumes);

      for (const workspace of workspaces) {
        const volumeMount = workspace.includes(':')
          ? workspace
          : `${workspace}:/root/${workspace.split('/').pop()}`;

        if (!existingVolumes.has(volumeMount)) {
          compose.services.opencode.volumes.push(volumeMount);
          existingVolumes.add(volumeMount);
        }
      }
    }
  }

  const hasHarborCli = services.includes('harbor-cli');

  // Detect active backends using shared utility
  const activeBackends = getAllActiveBackends(services);

  if (activeBackends.length === 0) {
    if (hasHarborCli) {
      // Chain through the setpriv wrapper from compose.opencode.yml so the
      // root chown + drop-to-host-user behavior is preserved.
      compose.services.opencode.entrypoint = [
        '/bin/bash',
        '/harbor-entrypoint.sh',
        '/bin/bash',
        '-c',
        `${generateHarborCliInitScript()}\nexec "$$@"`,
        '--',
      ];
    }
    return compose;
  }

  // Add depends_on for all active backends
  for (const backend of activeBackends) {
    addBackendDependency(compose.services.opencode, backend.service);
  }

  // Inject discovery script with only the active backends
  const discoveryScript = generateDiscoveryScript(activeBackends);
  // Chain through the setpriv wrapper so root chowns the mounts first, then
  // the discovery script and opencode itself run as the host user.
  compose.services.opencode.entrypoint = [
    '/bin/bash',
    '/harbor-entrypoint.sh',
    '/bin/bash',
    '-c',
    discoveryScript,
    '--',
  ];

  return compose;
}