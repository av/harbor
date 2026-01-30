import type { ComposeContext, ComposeObject } from './routines/composeTypes';

/**
 * OpenAI-compatible inference backends supported by OpenClaw.
 * Priority order: first match wins when multiple backends are active.
 */
const BACKENDS: Record<string, { url: string; name: string }> = {
  ollama: { url: 'http://ollama:11434', name: 'ollama' },
  llamacpp: { url: 'http://llamacpp:8080', name: 'llamacpp' },
  vllm: { url: 'http://vllm:8000', name: 'vllm' },
  tabbyapi: { url: 'http://tabbyapi:5000', name: 'tabbyapi' },
  mistralrs: { url: 'http://mistralrs:8021', name: 'mistralrs' },
  sglang: { url: 'http://sglang:30000', name: 'sglang' },
  lmdeploy: { url: 'http://lmdeploy:23333', name: 'lmdeploy' },
};

export default async function apply(ctx: ComposeContext): Promise<ComposeObject> {
  const { compose, services, explicitServices } = ctx;

  if (!compose.services?.openclaw) {
    return compose;
  }

  // Prioritize explicitly requested backends in user's order
  const explicitBackend = explicitServices
    .map(svc => [svc, BACKENDS[svc]] as const)
    .find(([, backend]) => backend)?.[0];

  // Fall back to first active backend (in BACKENDS order) if no explicit request
  const fallbackBackend = Object.keys(BACKENDS)
    .find(svc => services.includes(svc));

  const backendService = explicitBackend || fallbackBackend;

  if (!backendService) {
    // No backend detected - allow container to start for manual config
    return compose;
  }

  const { url, name } = BACKENDS[backendService];

  // Ensure environment object exists
  if (!compose.services.openclaw.environment) {
    compose.services.openclaw.environment = {};
  }

  // Inject backend connection details as environment variables
  if (Array.isArray(compose.services.openclaw.environment)) {
    compose.services.openclaw.environment.push(
      `HARBOR_BACKEND_NAME=${name}`,
      `HARBOR_BACKEND_URL=${url}`
    );
  } else {
    compose.services.openclaw.environment.HARBOR_BACKEND_NAME = name;
    compose.services.openclaw.environment.HARBOR_BACKEND_URL = url;
  }

  // Add depends_on for the detected backend
  const existingDeps = compose.services.openclaw.depends_on || [];
  const depsArray = Array.isArray(existingDeps)
    ? existingDeps
    : Object.keys(existingDeps);

  compose.services.openclaw.depends_on = [
    ...new Set([...depsArray, backendService])
  ];

  return compose;
}
