import type { ComposeConfig, ServiceRenderer, ServiceRendererContext } from '../types';
import { log } from '../utils';
import path from 'node:path';
import fs from 'node:fs';

const __dirname = import.meta.dirname!;

const renderers: Map<string, ServiceRenderer> = new Map();

export function registerRenderer(handle: string, renderer: ServiceRenderer) {
  renderers.set(handle, renderer);
  log.debug(`Registered renderer for service: ${handle}`);
}

export async function applyRenderers(merged: ComposeConfig): Promise<void> {
  const services = merged.services ?? {};

  for (const [handle, serviceConfig] of Object.entries(services)) {
    const renderer = renderers.get(handle);

    if (renderer) {
      log.debug(`Applying renderer for service: ${handle}`);
      const ctx: ServiceRendererContext = {
        handle,
        merged,
        serviceConfig,
      };
      await renderer(ctx);
    }
  }
}

export async function loadRenderers(): Promise<void> {
  const files = await fs.promises.readdir(__dirname);
  const tsFiles = files.filter((f) => f.endsWith('.ts') && f !== 'index.ts');

  for (const file of tsFiles) {
    const modulePath = path.join(__dirname, file);
    const mod = await import(modulePath) as { default?: ServiceRenderer; handle?: string };

    if (mod.default && mod.handle) {
      registerRenderer(mod.handle, mod.default);
    }
  }
}
