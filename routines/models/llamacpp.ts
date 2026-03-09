/// <reference lib="deno.ns" />
import process from 'node:process';
import { log } from '../utils';
import type { ModelEntry } from './types';

// @ts-ignore npm specifier
import { parseGGUFQuantLabel } from 'npm:@huggingface/gguf';

const GGUF_WORKER_URL = new URL('./gguf-worker.ts', import.meta.url);
let workerIdCounter = 0;

type GgufDetails = { architecture?: string; parameters?: string; quantization?: string; contextLength?: number };

function resolveGgufWithWorker(filePath: string, filename: string): Promise<GgufDetails> {
  return new Promise((resolve) => {
    const id = workerIdCounter++;
    const worker = new Worker(GGUF_WORKER_URL, { type: 'module' });
    worker.onmessage = (e: MessageEvent) => {
      worker.terminate();
      resolve(e.data.result);
    };
    worker.onerror = () => {
      worker.terminate();
      resolve({ quantization: parseGGUFQuantLabel(filename) ?? undefined });
    };
    worker.postMessage({ filePath, filename, id });
  });
}

// Derive canonical "org/repo" from a manifest filename.
// New format: manifest={org}={repo}={tag}.json (3+ "=" parts)
// Old format: manifest={org}_{repo}={tag}.json  (2   "=" parts, first split on "_")
function parseManifestCanonicalId(filename: string): string | null {
  const stem = filename.slice('manifest='.length, -'.json'.length);
  const parts = stem.split('=');
  if (parts.length >= 3) {
    return `${parts[0]}/${parts[1]}`;
  } else if (parts.length === 2) {
    const idx = parts[0].indexOf('_');
    if (idx <= 0) return null;
    return `${parts[0].slice(0, idx)}/${parts[0].slice(idx + 1)}`;
  }
  return null;
}

async function buildPrefixMap(cacheDir: string): Promise<Map<string, string>> {
  const prefixMap = new Map<string, string>();
  try {
    for await (const entry of Deno.readDir(cacheDir)) {
      if (!entry.isFile || !entry.name.startsWith('manifest=') || !entry.name.endsWith('.json')) continue;
      const canonicalId = parseManifestCanonicalId(entry.name);
      if (!canonicalId) continue;
      const [org, repo] = canonicalId.split('/');
      prefixMap.set(`${org}_${repo}_`, canonicalId);
    }
  } catch { /* ignore */ }
  return prefixMap;
}

async function resolveFileCanonicalId(
  name: string,
  relDir: string,
  cacheDir: string,
  prefixMap: Map<string, string>,
): Promise<string> {
  if (relDir) return relDir;
  for (const [prefix, id] of prefixMap) {
    if (name.startsWith(prefix)) return id;
  }
  const sidecarPath = `${cacheDir}/${name}.json`;
  try {
    const sidecar = JSON.parse(await Deno.readTextFile(sidecarPath));
    const url: string = sidecar.url ?? '';
    const m = url.match(/huggingface\.co\/([^/]+\/[^/]+)\//);
    if (m) return m[1];
  } catch { /* no sidecar */ }
  return name.replace(/\.gguf$/i, '');
}

export async function listLlamacppModels(): Promise<ModelEntry[]> {
  const cacheDir = process.env.HARBOR_LLAMACPP_CACHE;
  if (!cacheDir) return [];

  try {
    const s = await Deno.stat(cacheDir);
    if (!s.isDirectory) return [];
  } catch {
    return [];
  }

  const prefixMap = await buildPrefixMap(cacheDir);

  type FileItem = { fullPath: string; name: string; stat: Deno.FileInfo; relDir: string };
  const items: FileItem[] = [];

  async function collectDir(dir: string) {
    try {
      for await (const entry of Deno.readDir(dir)) {
        const fullPath = dir + '/' + entry.name;
        if (entry.isDirectory) {
          await collectDir(fullPath);
        } else if (entry.isFile && entry.name.endsWith('.gguf')) {
          const stat = await Deno.stat(fullPath);
          const relDir = dir === cacheDir ? '' : dir.slice(cacheDir.length + 1);
          items.push({ fullPath, name: entry.name, stat, relDir });
        }
      }
    } catch (err) {
      log.warn(`llamacpp scan error in ${dir}: ${err}`);
    }
  }

  await collectDir(cacheDir);

  return Promise.all(
    items
      .filter(item => !item.name.toLowerCase().includes('mmproj'))
      .map(async item => {
        const canonicalId = await resolveFileCanonicalId(item.name, item.relDir, cacheDir, prefixMap);
        const details = await resolveGgufWithWorker(item.fullPath, item.name);
        const quant =
          details.quantization ??
          parseGGUFQuantLabel(item.name) ??
          item.name.replace(/\.gguf$/i, '');
        return {
          source: 'llamacpp' as const,
          model: `${canonicalId}:${quant}`,
          size: item.stat.size,
          modified: item.stat.mtime ? item.stat.mtime.toISOString() : new Date().toISOString(),
          details: {
            ...(details.architecture && { architecture: details.architecture }),
            ...(details.parameters && { parameters: details.parameters }),
            ...(details.quantization && { quantization: details.quantization }),
            ...(details.contextLength && { context_length: details.contextLength }),
          },
        } satisfies ModelEntry;
      })
  );
}

export async function removeLlamacppModel(modelSpec: string): Promise<boolean> {
  const cacheDir = process.env.HARBOR_LLAMACPP_CACHE;
  if (!cacheDir) return false;

  const colonIdx = modelSpec.indexOf(':');
  const repoSpec = colonIdx >= 0 ? modelSpec.slice(0, colonIdx) : modelSpec;
  const quantTag = colonIdx >= 0 ? modelSpec.slice(colonIdx + 1) : null;
  const slashIdx = repoSpec.indexOf('/');
  const org = slashIdx >= 0 ? repoSpec.slice(0, slashIdx) : repoSpec;
  const repo = slashIdx >= 0 ? repoSpec.slice(slashIdx + 1) : '';

  let removed = false;

  function quantMatches(filename: string): boolean {
    if (!quantTag) return true;
    const fileQuant = parseGGUFQuantLabel(filename);
    const stem = filename.replace(/\.gguf$/i, '');
    return fileQuant === quantTag || stem === quantTag || stem.endsWith(`_${quantTag}`);
  }

  // Subdirectory layout: {cacheDir}/{org}/{repo}/{file}.gguf
  if (org && repo) {
    const subRepoDir = `${cacheDir}/${org}/${repo}`;
    try {
      for await (const entry of Deno.readDir(subRepoDir)) {
        if (!entry.isFile || !entry.name.endsWith('.gguf')) continue;
        if (!quantMatches(entry.name)) continue;
        await Deno.remove(`${subRepoDir}/${entry.name}`);
        try { await Deno.remove(`${subRepoDir}/${entry.name}.json`); } catch { /* no sidecar */ }
        removed = true;
      }
      const isEmpty = async (dir: string) => {
        for await (const _ of Deno.readDir(dir)) return false;
        return true;
      };
      if (await isEmpty(subRepoDir)) {
        await Deno.remove(subRepoDir);
        const orgDir = `${cacheDir}/${org}`;
        if (await isEmpty(orgDir)) await Deno.remove(orgDir);
      }
    } catch { /* subdir doesn't exist */ }
  }

  // Flat file layout: {org}_{repo}_{file}.gguf
  if (org && repo) {
    const flatPrefix = `${org}_${repo}_`;
    try {
      for await (const entry of Deno.readDir(cacheDir)) {
        if (!entry.isFile || !entry.name.startsWith(flatPrefix) || !entry.name.endsWith('.gguf')) continue;
        if (!quantMatches(entry.name)) continue;
        await Deno.remove(`${cacheDir}/${entry.name}`);
        try { await Deno.remove(`${cacheDir}/${entry.name}.json`); } catch { /* no sidecar */ }
        removed = true;
      }
    } catch { /* ignore */ }
  }

  // Manifest files — only when removing the entire repo (no quant filter)
  if (!quantTag && org && repo) {
    try {
      for await (const entry of Deno.readDir(cacheDir)) {
        if (!entry.isFile || !entry.name.startsWith('manifest=')) continue;
        if (entry.name.includes(`=${org}=${repo}=`) || entry.name.includes(`=${org}_${repo}=`)) {
          await Deno.remove(`${cacheDir}/${entry.name}`);
          removed = true;
        }
      }
    } catch { /* ignore */ }
  }

  // Sidecar scan: flat .gguf files whose repo identity comes only from a .gguf.json sidecar
  if (org && repo) {
    const prefixMap = await buildPrefixMap(cacheDir);
    try {
      for await (const entry of Deno.readDir(cacheDir)) {
        if (!entry.isFile || !entry.name.endsWith('.gguf')) continue;
        const canonicalId = await resolveFileCanonicalId(entry.name, '', cacheDir, prefixMap);
        if (canonicalId !== repoSpec) continue;
        if (!quantMatches(entry.name)) continue;
        await Deno.remove(`${cacheDir}/${entry.name}`);
        try { await Deno.remove(`${cacheDir}/${entry.name}.json`); } catch { /* no sidecar */ }
        removed = true;
      }
    } catch { /* ignore */ }
  }

  return removed;
}
