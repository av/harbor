/// <reference lib="deno.ns" />
import process from 'node:process';
import { log } from '../utils';
import type { HfRepoInfo, HfFileInfo } from './types';

// @ts-ignore npm specifier
import { scanCacheDir } from 'npm:@huggingface/hub';
// @ts-ignore npm specifier
import { parseGGUFQuantLabel } from 'npm:@huggingface/gguf';

function getHfCache(): string | null {
  return process.env.HARBOR_HF_CACHE ?? null;
}

async function dirExists(p: string): Promise<boolean> {
  try {
    const s = await Deno.stat(p);
    return s.isDirectory;
  } catch {
    return false;
  }
}

async function readJsonFile(p: string): Promise<Record<string, unknown> | null> {
  try {
    const raw = await Deno.readTextFile(p);
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

const GGUF_WORKER_URL = new URL('./gguf-worker.ts', import.meta.url);
let workerIdCounter = 0;

function resolveGgufDetails(filePath: string, filename: string): Promise<HfRepoInfo['details']> {
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

async function scanLooseGgufs(dir: string): Promise<HfRepoInfo[]> {
  if (!(await dirExists(dir))) return [];
  type RawItem = { name: string; filePath: string; size: number; mtime: Date };
  const rawItems: RawItem[] = [];
  try {
    for await (const entry of Deno.readDir(dir)) {
      if (entry.isFile && entry.name.endsWith('.gguf')) {
        const filePath = dir + '/' + entry.name;
        const stat = await Deno.stat(filePath);
        rawItems.push({ name: entry.name, filePath, size: stat.size, mtime: stat.mtime ?? new Date() });
      }
    }
  } catch (err) {
    log.warn(`HF loose GGUF scan error in ${dir}: ${err}`);
    return [];
  }
  return Promise.all(rawItems.map(async ({ name, filePath, size, mtime }) => {
    const details = await resolveGgufDetails(filePath, name);
    return {
      repo: name.replace(/\.gguf$/i, ''),
      path: filePath,
      size,
      modified: mtime,
      files: [{ name, size }],
      details,
    };
  }));
}

export async function listHfModels(): Promise<HfRepoInfo[]> {
  const hfCache = getHfCache();
  if (!hfCache) return [];
  if (!(await dirExists(hfCache))) return [];

  // deno-lint-ignore no-explicit-any
  let cacheInfo: any;
  try {
    cacheInfo = await scanCacheDir(hfCache + '/hub');
  } catch (err) {
    log.warn(`Failed to scan HF cache at ${hfCache}: ${(err as Error).message}`);
    return [];
  }

  // deno-lint-ignore no-explicit-any
  async function processRepo(repo: any): Promise<HfRepoInfo | null> {
    // deno-lint-ignore no-explicit-any
    const repoAny = repo as any;
    const repoId: string = repoAny.id?.name ?? repoAny.repoId;
    const repoType: string = repoAny.id?.type ?? repoAny.repoType;
    const repoPath: string = repoAny.path ?? repoAny.repoPath ?? '';
    const repoSizeOnDisk: number = repoAny.size ?? repoAny.sizeOnDisk ?? 0;

    if (repoType !== 'model') return null;

    // deno-lint-ignore no-explicit-any
    const revisions: any[] = Array.from(repo.revisions ?? []);
    if (revisions.length === 0) return null;

    const latest = revisions.reduce((a, b) =>
      (a.lastModifiedAt?.getTime() ?? 0) >= (b.lastModifiedAt?.getTime() ?? 0) ? a : b
    );

    // deno-lint-ignore no-explicit-any
    const allFiles: any[] = Array.from(latest.files ?? []);

    // Normalise file objects: new API has { path (full), blob: { path, size } }
    // Old API had { fileName, size, blob: { path } }
    // deno-lint-ignore no-explicit-any
    const normFile = (f: any) => ({
      fileName: f.fileName ?? f.path?.split('/').pop() ?? '',
      size: f.size ?? f.blob?.size ?? 0,
      blobPath: f.blob?.path as string | undefined,
    });

    const normFiles = allFiles.map(normFile);
    const ggufFiles = normFiles.filter(f => f.fileName?.endsWith('.gguf'));
    const safetensorFiles = normFiles.filter(f =>
      f.fileName?.endsWith('.safetensors') || f.fileName?.endsWith('.safetensors.index.json')
    );

    const significantFiles: HfFileInfo[] = [];
    let details: HfRepoInfo['details'] = {};

    if (ggufFiles.length > 0) {
      for (const f of ggufFiles) {
        significantFiles.push({ name: f.fileName, size: f.size });
      }
      if (ggufFiles[0].blobPath) {
        details = await resolveGgufDetails(ggufFiles[0].blobPath, ggufFiles[0].fileName);
      } else {
        const quantization = parseGGUFQuantLabel(ggufFiles[0].fileName) ?? undefined;
        details = { quantization };
      }
    } else if (safetensorFiles.length > 0) {
      for (const f of safetensorFiles.filter(sf => sf.fileName?.endsWith('.safetensors'))) {
        significantFiles.push({ name: f.fileName, size: f.size });
      }
      const configFile = normFiles.find(f => f.fileName === 'config.json');
      if (configFile?.blobPath) {
        const config = await readJsonFile(configFile.blobPath);
        if (config) {
          details = {
            architecture: config['model_type'] as string | undefined,
            contextLength: config['max_position_embeddings'] as number | undefined,
            dtype: config['torch_dtype'] as string | undefined,
          };
        }
      }
    }

    const totalSize = significantFiles.reduce((s, f) => s + f.size, 0) || repoSizeOnDisk;

    return {
      repo: repoId,
      path: repoPath,
      size: totalSize,
      modified: latest.lastModifiedAt ?? new Date(0),
      files: significantFiles,
      details,
    };
  }

  const [repoResults, looseGgufs, ggufSubdir] = await Promise.all([
    Promise.all(Array.from(cacheInfo.repos).map(processRepo)),
    scanLooseGgufs(hfCache),
    scanLooseGgufs(hfCache + '/gguf'),
  ]);

  const results: HfRepoInfo[] = [
    ...(repoResults.filter((r): r is HfRepoInfo => r !== null)),
    ...looseGgufs,
    ...ggufSubdir,
  ];

  return results;
}

export async function removeHfModel(modelSpec: string): Promise<boolean> {
  const hfCache = getHfCache();
  if (!hfCache) return false;

  const dirName = 'models--' + modelSpec.replace('/', '--');
  const dirPath = `${hfCache}/hub/${dirName}`;

  if (await dirExists(dirPath)) {
    await Deno.remove(dirPath, { recursive: true });
    return true;
  }

  const baseName = modelSpec.replace(/\.gguf$/i, '');
  const ggufName = baseName + '.gguf';
  for (const loosePath of [`${hfCache}/${ggufName}`, `${hfCache}/gguf/${ggufName}`]) {
    try {
      await Deno.stat(loosePath);
      await Deno.remove(loosePath);
      return true;
    } catch {
      // not found, try next
    }
  }

  return false;
}
