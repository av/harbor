/**
 * Shared utilities for integrating Harbor services with OpenAI-compatible inference backends.
 *
 * This module provides:
 * - Centralized backend registry
 * - Common detection logic
 * - Dependency management helpers
 * - Environment injection utilities
 */

import type { ServiceDefinition } from './composeTypes';

/**
 * Backend configuration for OpenAI-compatible inference services.
 */
export interface BackendInfo {
  /** Internal Docker network URL */
  url: string;
  /** Display name (used in logs, configs, etc.) */
  name: string;
}

/**
 * Result of backend detection.
 */
export interface DetectedBackend {
  /** Service name (e.g., "ollama", "vllm") */
  service: string;
  /** Backend configuration */
  info: BackendInfo;
}

/**
 * Registry of OpenAI-compatible inference backends supported by Harbor.
 *
 * These backends all expose a /v1/chat/completions endpoint compatible
 * with OpenAI's API format, making them interchangeable for most services.
 *
 * Order matters: when multiple backends are active without explicit selection,
 * the first one in this object is used.
 */
export const OPENAI_COMPATIBLE_BACKENDS: Record<string, BackendInfo> = {
  ollama: { url: 'http://ollama:11434', name: 'Ollama' },
  llamacpp: { url: 'http://llamacpp:8080', name: 'Llama.cpp' },
  vllm: { url: 'http://vllm:8000', name: 'vLLM' },
  tabbyapi: { url: 'http://tabbyapi:5000', name: 'TabbyAPI' },
  mistralrs: { url: 'http://mistralrs:8021', name: 'Mistral.rs' },
  sglang: { url: 'http://sglang:30000', name: 'SGLang' },
  lmdeploy: { url: 'http://lmdeploy:23333', name: 'LMDeploy' },
  aphrodite: { url: 'http://aphrodite:2242', name: 'Aphrodite' },
  ktransformers: { url: 'http://ktransformers:8088', name: 'KTransformers' },
};

/**
 * Detects which OpenAI-compatible backend to use based on active services.
 *
 * Detection priority:
 * 1. First explicitly requested backend from explicitServices (preserves user order)
 * 2. First active backend in BACKENDS order (deterministic fallback)
 * 3. null if no backends are active
 *
 * @param services - All active services in the compose stack
 * @param explicitServices - Services explicitly requested by user (preserves order)
 * @param backends - Backend registry to use (defaults to OPENAI_COMPATIBLE_BACKENDS)
 * @returns DetectedBackend or null if no backend found
 *
 * @example
 * ```ts
 * // User runs: harbor up myservice ollama vllm
 * // explicitServices = ['myservice', 'ollama', 'vllm']
 * // Result: { service: 'ollama', info: { url: '...', name: 'Ollama' } }
 *
 * // User runs: harbor up myservice (ollama already running)
 * // explicitServices = ['myservice'], services = ['myservice', 'ollama']
 * // Result: { service: 'ollama', info: { url: '...', name: 'Ollama' } }
 * ```
 */
export function detectBackend(
  services: string[],
  explicitServices: string[],
  backends: Record<string, BackendInfo> = OPENAI_COMPATIBLE_BACKENDS
): DetectedBackend | null {
  // Priority 1: Explicitly requested backends (in user's order)
  const explicitBackend = explicitServices
    .map((svc: string) => [svc, backends[svc]] as const)
    .find(([, backend]: readonly [string, BackendInfo | undefined]) => backend)?.[0];

  // Priority 2: First active backend in registry order (deterministic)
  const fallbackBackend = Object.keys(backends)
    .find(svc => services.includes(svc));

  const backendService = explicitBackend || fallbackBackend;

  if (!backendService) {
    return null;
  }

  return {
    service: backendService,
    info: backends[backendService]
  };
}

/**
 * Gets all active backends from the services list.
 *
 * Unlike detectBackend(), this returns ALL active backends, not just the first one.
 * Useful for services that need to integrate with multiple backends simultaneously.
 *
 * @param services - All active services in the compose stack
 * @param backends - Backend registry to use (defaults to OPENAI_COMPATIBLE_BACKENDS)
 * @returns Array of detected backends with their service names
 *
 * @example
 * ```ts
 * // ollama and vllm are both active
 * const backends = getAllActiveBackends(['myservice', 'ollama', 'vllm']);
 * // Result: [
 * //   { service: 'ollama', info: { url: '...', name: 'Ollama' } },
 * //   { service: 'vllm', info: { url: '...', name: 'vLLM' } }
 * // ]
 * ```
 */
export function getAllActiveBackends(
  services: string[],
  backends: Record<string, BackendInfo> = OPENAI_COMPATIBLE_BACKENDS
): DetectedBackend[] {
  return Object.entries(backends)
    .filter(([svc]) => services.includes(svc))
    .map(([svc, info]) => ({ service: svc, info }));
}

/**
 * Adds a backend service to the depends_on list of a compose service.
 *
 * Handles both array and object formats for depends_on, deduplicates entries.
 *
 * @param service - Compose service definition to modify
 * @param backendService - Backend service name to add as dependency
 *
 * @example
 * ```ts
 * addBackendDependency(compose.services.myservice, 'ollama');
 * // Result: myservice.depends_on = [...existing, 'ollama'] (deduplicated)
 * ```
 */
export function addBackendDependency(
  service: ServiceDefinition,
  backendService: string
): void {
  const existingDeps = service.depends_on || [];
  const depsArray = Array.isArray(existingDeps)
    ? existingDeps
    : Object.keys(existingDeps);

  service.depends_on = [
    ...new Set([...depsArray, backendService])
  ];
}

/**
 * Injects backend connection details as environment variables.
 *
 * Sets HARBOR_BACKEND_NAME and HARBOR_BACKEND_URL in the service's environment.
 * Handles both array and object formats for environment variables.
 *
 * @param service - Compose service definition to modify
 * @param backend - Detected backend to inject
 *
 * @example
 * ```ts
 * injectBackendEnv(compose.services.nanobot, {
 *   service: 'ollama',
 *   info: { url: 'http://ollama:11434', name: 'Ollama' }
 * });
 * // Result: environment includes HARBOR_BACKEND_NAME=Ollama, HARBOR_BACKEND_URL=http://ollama:11434
 * ```
 */
export function injectBackendEnv(
  service: ServiceDefinition,
  backend: DetectedBackend
): void {
  // Ensure environment object exists
  if (!service.environment) {
    service.environment = {};
  }

  // Inject backend connection details
  if (Array.isArray(service.environment)) {
    service.environment.push(
      `HARBOR_BACKEND_NAME=${backend.info.name}`,
      `HARBOR_BACKEND_URL=${backend.info.url}`
    );
  } else {
    service.environment.HARBOR_BACKEND_NAME = backend.info.name;
    service.environment.HARBOR_BACKEND_URL = backend.info.url;
  }
}
