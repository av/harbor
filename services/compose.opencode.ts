import type { ComposeContext, ComposeObject } from './routines/composeTypes';

/**
 * OpenAI-compatible inference backends supported for auto-discovery.
 * Each backend exposes a /v1/models endpoint.
 */
const BACKENDS: Record<string, { url: string; name: string }> = {
  ollama: { url: 'http://ollama:11434', name: 'Ollama' },
  llamacpp: { url: 'http://llamacpp:8080', name: 'Llama.cpp' },
  vllm: { url: 'http://vllm:8000', name: 'vLLM' },
  tabbyapi: { url: 'http://tabbyapi:5000', name: 'TabbyAPI' },
  mistralrs: { url: 'http://mistralrs:8021', name: 'Mistral.rs' },
  sglang: { url: 'http://sglang:30000', name: 'SGLang' },
  lmdeploy: { url: 'http://lmdeploy:23333', name: 'LMDeploy' },
};

/**
 * Generates an inline bash script that:
 * 1. Waits for each backend to become available
 * 2. Queries /v1/models to discover available models
 * 3. Writes an opencode.json config with discovered providers
 * 4. Executes opencode with original arguments
 *
 * Note: All $ must be escaped as $$ for Docker Compose interpolation.
 */
function generateDiscoveryScript(backends: Array<{ svc: string; url: string; name: string }>): string {
  const backendList = backends.map(b => `${b.svc}=${b.url}`).join(' ');

  // Note: Using string concatenation for bash syntax that conflicts with JS template literals
  const configDirDefault = '$$' + '{OPENCODE_CONFIG_DIR:-/root/.config/opencode}';
  const backendNameExtract = '$$' + '{backend%%=*}';
  const backendUrlExtract = '$$' + '{backend#*=}';

  return `
set -e
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
  curl -sf "$$1/v1/models" 2>/dev/null
}

echo '{"$$schema":"https://opencode.ai/config.json","provider":{' > "$$CONFIG_FILE"
first=true

for backend in ${backendList}; do
  name="${backendNameExtract}"
  url="${backendUrlExtract}"

  echo "Waiting for $$name at $$url..."
  wait_for "$$url" || { echo "Backend $$name not available after 30s, skipping"; continue; }

  echo "Discovering models from $$name..."
  models=$$(discover "$$url") || { echo "Failed to get models from $$name"; continue; }

  model_ids=$$(echo "$$models" | grep -o '"id":"[^"]*"' | cut -d'"' -f4)
  [ -z "$$model_ids" ] && { echo "No models found for $$name"; continue; }

  $$first || echo ',' >> "$$CONFIG_FILE"
  first=false

  cat >> "$$CONFIG_FILE" << PROVIDER
"harbor-$$name":{"npm":"@ai-sdk/openai-compatible","name":"$$name (Harbor)","options":{"baseURL":"$$url/v1","apiKey":"sk-harbor"},"models":{
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

  // Detect active backends from ctx.services
  const activeBackends = Object.entries(BACKENDS)
    .filter(([svc]) => services.includes(svc))
    .map(([svc, cfg]) => ({ svc, ...cfg }));

  if (activeBackends.length === 0) {
    return compose;
  }

  // Add depends_on for active backends
  const existingDeps = compose.services.opencode.depends_on || [];
  const depsArray = Array.isArray(existingDeps)
    ? existingDeps
    : Object.keys(existingDeps);
  compose.services.opencode.depends_on = [
    ...new Set([...depsArray, ...activeBackends.map(b => b.svc)])
  ];

  // Inject discovery script with only the active backends
  const discoveryScript = generateDiscoveryScript(activeBackends);
  compose.services.opencode.entrypoint = ['/bin/bash', '-c', discoveryScript, '--'];

  return compose;
}