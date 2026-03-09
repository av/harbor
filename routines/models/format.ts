import type { ModelEntry } from './types';

const COL_SOURCE = 8;
const COL_SIZE = 10;
const FILE_INDENT = 11;

export function formatBytes(bytes: number): string {
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
  if (bytes >= 1e6) return `${Math.round(bytes / 1e6)} MB`;
  if (bytes >= 1e3) return `${Math.round(bytes / 1e3)} KB`;
  return `${bytes} B`;
}

function padRight(s: string, n: number): string {
  return s + ' '.repeat(Math.max(1, n - s.length));
}

function formatDetails(entry: ModelEntry): string {
  const d = entry.details;
  const parts: string[] = [];

  if (entry.source === 'ollama') {
    if (d.family) parts.push(String(d.family));
    if (d.parameters) parts.push(String(d.parameters));
    if (d.quantization) parts.push(String(d.quantization));
  } else {
    const arch = d.architecture ?? d.family;
    if (arch) parts.push(String(arch));
    if (d.parameters) parts.push(String(d.parameters));
    if (d.contextLength) parts.push(`${d.contextLength}ctx`);
    if (d.dtype) parts.push(String(d.dtype).toUpperCase());
    if (!d.contextLength && !d.dtype && d.quantization) parts.push(String(d.quantization));
    if (d.files) parts.push(`${d.files} files`);
  }

  return parts.join(' ');
}

export function formatTable(entries: ModelEntry[]): string {
  const lines: string[] = [];

  const fileNames = entries.flatMap(e => e.files?.map(f => f.name) ?? []);
  const COL_MODEL = Math.max(
    'MODEL'.length,
    ...entries.map(e => e.model.length),
    ...fileNames.map(n => FILE_INDENT - COL_SOURCE + n.length),
  ) + 2;

  lines.push(
    padRight('SOURCE', COL_SOURCE) +
    padRight('MODEL', COL_MODEL) +
    padRight('SIZE', COL_SIZE) +
    'DETAILS'
  );

  for (const entry of entries) {
    const size = formatBytes(entry.size);
    lines.push(
      padRight(entry.source, COL_SOURCE) +
      padRight(entry.model, COL_MODEL) +
      padRight(size, COL_SIZE) +
      formatDetails(entry)
    );

    if (entry.files && entry.files.length > 0) {
      for (const f of entry.files) {
        const fSize = formatBytes(f.size);
        lines.push(
          ' '.repeat(FILE_INDENT) +
          padRight(f.name, COL_MODEL + COL_SOURCE - FILE_INDENT) +
          fSize
        );
      }
    }
  }

  return lines.join('\n');
}

export function formatJson(entries: ModelEntry[]): string {
  return JSON.stringify(
    entries.map(e => ({
      source: e.source,
      model: e.model,
      size: e.size,
      modified: e.modified,
      ...(e.files ? { files: e.files } : {}),
      details: e.details,
    })),
    null,
    2
  );
}
