import type { ComposeContext, ComposeObject } from '../routines/composeTypes';
import { detectBackend, addBackendDependency, injectBackendEnv } from '../routines/backendIntegration';

export default function apply(ctx: ComposeContext): ComposeObject {
  const { compose, services, explicitServices } = ctx;

  if (!compose.services?.nanobot) {
    return compose;
  }

  // Detect active backend using shared utility
  const backend = detectBackend(services, explicitServices);

  if (!backend) {
    // No backend detected - allow container to start for manual config
    return compose;
  }

  // Inject backend connection details as environment variables
  injectBackendEnv(compose.services.nanobot, backend);

  // Add depends_on for the detected backend
  addBackendDependency(compose.services.nanobot, backend.service);

  return compose;
}
