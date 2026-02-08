import type { ComposeContext, ComposeObject } from '../routines/composeTypes';
import { detectBackend, addBackendDependency, injectBackendEnv } from '../routines/backendIntegration';

export default function apply(ctx: ComposeContext): ComposeObject {
  const { compose, services, explicitServices } = ctx;

  if (!compose.services?.postiz) {
    return compose;
  }

  const backend = detectBackend(services, explicitServices);

  if (!backend) {
    return compose;
  }

  injectBackendEnv(compose.services.postiz, backend);
  addBackendDependency(compose.services.postiz, backend.service);

  compose.services.postiz.environment = compose.services.postiz.environment || {};
  compose.services.postiz.environment['OPENAI_API_KEY'] = 'sk-harbor';
  compose.services.postiz.environment['OPENAI_BASE_URL'] = `${backend.info.url}/v1`;

  return compose;
}
