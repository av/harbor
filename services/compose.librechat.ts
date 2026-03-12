import { join } from 'jsr:@std/path';
import type { ComposeContext, ComposeObject } from '../routines/composeTypes';

function randomHex(bytes: number): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(bytes)), (b) =>
    b.toString(16).padStart(2, '0')
  ).join('');
}

function parseEnv(text: string): Record<string, string> {
  const result: Record<string, string> = {};
  for (const line of text.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const eq = trimmed.indexOf('=');
    if (eq === -1) continue;
    result[trimmed.slice(0, eq)] = trimmed.slice(eq + 1);
  }
  return result;
}

function serializeEnv(vars: Record<string, string>): string {
  return Object.entries(vars).map(([k, v]) => `${k}=${v}`).join('\n') + '\n';
}

export default async function apply(ctx: ComposeContext): Promise<ComposeObject> {
  const { compose, dir } = ctx;

  if (!compose.services?.librechat) {
    return compose;
  }

  const envPath = join(dir, 'services', 'librechat', '.env');

  let existing = '';
  try {
    existing = await Deno.readTextFile(envPath);
  } catch {
    // file doesn't exist yet
  }

  const vars = parseEnv(existing);
  let changed = false;

  const required: Record<string, () => string> = {
    CREDS_KEY: () => randomHex(32),
    CREDS_IV: () => randomHex(16),
    JWT_SECRET: () => randomHex(32),
    JWT_REFRESH_SECRET: () => randomHex(32),
  };

  for (const [key, generate] of Object.entries(required)) {
    if (!vars[key]) {
      vars[key] = generate();
      changed = true;
    }
  }

  if (changed) {
    await Deno.writeTextFile(envPath, serializeEnv(vars));
  }

  return compose;
}
