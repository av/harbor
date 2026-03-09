import process from 'node:process';
import { log } from '../utils';
import type { OllamaModel } from './types';

function getOllamaUrl(): string {
  return process.env.HARBOR_OLLAMA_URL || 'http://ollama:11434';
}

export async function listOllamaModels(): Promise<OllamaModel[]> {
  const url = `${getOllamaUrl()}/api/tags`;
  try {
    const res = await fetch(url);
    if (!res.ok) {
      log.warn(`Ollama returned HTTP ${res.status} from ${url}`);
      return [];
    }
    const data = await res.json();
    return (data.models ?? []) as OllamaModel[];
  } catch (err) {
    log.warn(`Could not reach Ollama at ${url}: ${(err as Error).message}`);
    return [];
  }
}

export async function removeOllamaModel(name: string): Promise<boolean> {
  const url = `${getOllamaUrl()}/api/delete`;
  const res = await fetch(url, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: name }),
  });
  if (res.status === 200) return true;
  if (res.status === 404) return false;
  const body = await res.text().catch(() => '');
  throw new Error(`Ollama delete failed (HTTP ${res.status}): ${body}`);
}
