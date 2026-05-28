import { log } from '../utils';
import type { ModelEntry } from './types';

type ListOptions = {
  source: 'dmr' | 'mlx';
  url: string | undefined;
  apiKey?: string;
};

function normalizeBaseUrl(url: string): string {
  return url.replace(/\/+$/, '');
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function modelId(value: unknown): string | null {
  if (typeof value === 'string') return value;
  const record = asRecord(value);
  const id = record.id ?? record.name ?? record.model ?? record.root;
  return typeof id === 'string' && id ? id : null;
}

function modelSize(value: unknown): number {
  const record = asRecord(value);
  const size = record.size ?? record.size_on_disk ?? record.size_bytes;
  return typeof size === 'number' ? size : 0;
}

function modelModified(value: unknown): string {
  const record = asRecord(value);
  const modified = record.modified ?? record.modified_at ?? record.created_at ?? record.created;
  if (typeof modified === 'string') return modified;
  if (typeof modified === 'number') return new Date(modified * 1000).toISOString();
  return new Date(0).toISOString();
}

function modelDetails(value: unknown): Record<string, string | number | string[]> {
  const record = asRecord(value);
  const details = asRecord(record.details);
  const result: Record<string, string | number | string[]> = {};

  for (const [key, raw] of Object.entries({ ...record, ...details })) {
    if (['id', 'name', 'model', 'root', 'size', 'size_on_disk', 'size_bytes', 'modified', 'modified_at', 'created', 'created_at'].includes(key)) {
      continue;
    }
    if (typeof raw === 'string' || typeof raw === 'number') {
      result[key] = raw;
    } else if (Array.isArray(raw) && raw.every(item => typeof item === 'string')) {
      result[key] = raw;
    }
  }

  return result;
}

function extractModels(payload: unknown): unknown[] {
  if (Array.isArray(payload)) return payload;
  const record = asRecord(payload);
  if (Array.isArray(record.data)) return record.data;
  if (Array.isArray(record.models)) return record.models;
  return [];
}

export async function listOpenAiCompatibleModels(options: ListOptions): Promise<ModelEntry[]> {
  if (!options.url) return [];

  const endpoint = `${normalizeBaseUrl(options.url)}/v1/models`;
  try {
    const headers: Record<string, string> = {};
    if (options.apiKey) {
      headers.Authorization = `Bearer ${options.apiKey}`;
    }

    const res = await fetch(endpoint, { headers });
    if (!res.ok) {
      log.warn(`${options.source} returned HTTP ${res.status} from ${endpoint}`);
      return [];
    }

    const payload = await res.json();
    return extractModels(payload)
      .map((item): ModelEntry | null => {
        const id = modelId(item);
        if (!id) return null;
        return {
          source: options.source,
          model: id,
          size: modelSize(item),
          modified: modelModified(item),
          details: modelDetails(item),
        };
      })
      .filter((entry): entry is ModelEntry => entry !== null);
  } catch (err) {
    log.warn(`Could not reach ${options.source} at ${endpoint}: ${(err as Error).message}`);
    return [];
  }
}
