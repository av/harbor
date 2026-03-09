import type { ComposeContext, ComposeObject } from '../routines/composeTypes';
import { getOptionalValue, setValue } from '../routines/envManager';

const OPEN_TERMINAL_API_KEY = 'openterminal.api.key';
const LEGACY_DEFAULT_API_KEY = 'harbor-openterminal-change-me';

function generateApiKey(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
}

async function ensureApiKey(): Promise<void> {
  const currentValue = await getOptionalValue({ key: OPEN_TERMINAL_API_KEY });

  if (currentValue && currentValue.trim() && currentValue !== LEGACY_DEFAULT_API_KEY) {
    return;
  }

  await setValue({
    key: OPEN_TERMINAL_API_KEY,
    value: generateApiKey(),
  });
}

function isEnabled(value: string): boolean {
  return /^(1|true|yes|on)$/i.test(value.trim());
}

function setEnvironmentValue(compose: ComposeObject, key: string, value: string): void {
  const service = compose.services.openterminal;

  if (!service.environment) {
    service.environment = {};
  }

  if (Array.isArray(service.environment)) {
    const prefix = `${key}=`;
    service.environment = service.environment
      .filter((entry) => typeof entry !== 'string' || !entry.startsWith(prefix));
    service.environment.push(`${key}=${value}`);
    return;
  }

  service.environment[key] = value;
}

function buildExecuteDescription(opts: {
  hostWorkspace: string;
  dockerSocket: string;
  hasOllama: boolean;
  hasLlamacpp: boolean;
}): string {
  const notes = [
    'Harbor notes: use /home/user as the persistent sandbox workspace.',
    opts.hostWorkspace.trim()
      ? 'A host workspace is mounted at /workspace/host.'
      : 'No host workspace is mounted unless Harbor is configured to expose /workspace/host.',
    isEnabled(opts.dockerSocket)
      ? 'Docker CLI access is enabled through /var/run/docker.sock.'
      : 'Docker CLI is installed, but host Docker access is disabled unless Harbor mounts /var/run/docker.sock.',
  ];

  if (opts.hasOllama) {
    notes.push('When Ollama is running, use $$OLLAMA_HOST or $$HARBOR_OLLAMA_URL for native API calls and $$HARBOR_OLLAMA_OPENAI_URL for OpenAI-compatible calls.');
  }

  if (opts.hasLlamacpp) {
    notes.push('When llama.cpp is running, use $$HARBOR_LLAMACPP_OPENAI_URL with bearer token $$HARBOR_LLAMACPP_API_KEY.');
  }

  notes.push('Prefer the sandbox by default and only use /workspace/host or Docker when the task explicitly needs broader access.');

  return notes.join(' ');
}

export default async function apply(ctx: ComposeContext): Promise<ComposeObject> {
  const { compose, env, services } = ctx;

  if (!compose.services?.openterminal) {
    return compose;
  }

  await ensureApiKey();

  const service = compose.services.openterminal;
  const [hostWorkspace, dockerSocket] = await Promise.all([
    env.getValue('openterminal.host.workspace'),
    env.getValue('openterminal.docker.socket'),
  ]);

  if (!Array.isArray(service.volumes)) {
    service.volumes = service.volumes ? [service.volumes] : [];
  }

  const volumeSet = new Set(service.volumes);

  if (hostWorkspace.trim()) {
    volumeSet.add(`${hostWorkspace}:/workspace/host`);
  }

  if (isEnabled(dockerSocket)) {
    volumeSet.add('/var/run/docker.sock:/var/run/docker.sock');
  }

  service.volumes = [...volumeSet];
  setEnvironmentValue(
    compose,
    'OPEN_TERMINAL_EXECUTE_DESCRIPTION',
    buildExecuteDescription({
      hostWorkspace,
      dockerSocket,
      hasOllama: services.includes('ollama'),
      hasLlamacpp: services.includes('llamacpp'),
    }),
  );

  return compose;
}
