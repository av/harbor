/// <reference lib="deno.ns" />
import process from 'node:process';
import { log } from '../utils';
import type { HfRepoInfo, HfFileInfo } from './types';
import { compareGgufShardNames, parseGgufShardInfo } from './shards';

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

// Recursively walk a directory, collecting files with resolved blob paths.
// Used to supplement/replace @huggingface/hub's scanSnapshotDir which skips
// subdirectories, and to rescue repos the library drops entirely.
// Dedup by blob path makes this a no-op for files the library already found.
// deno-lint-ignore no-explicit-any
async function walkDir(dir: string, files: any[], knownBlobs: Set<string>): Promise<void> {
  let entries;
  try {
    entries = [];
    for await (const e of Deno.readDir(dir)) entries.push(e);
  } catch {
    return;
  }
  for (const entry of entries) {
    const fullPath = dir + '/' + entry.name;
    if (entry.isDirectory) {
      await walkDir(fullPath, files, knownBlobs);
    } else if (entry.isSymlink || entry.isFile) {
      try {
        const blobPath = await Deno.realPath(fullPath);
        if (knownBlobs.has(blobPath)) continue;
        knownBlobs.add(blobPath);
        const stat = await Deno.stat(blobPath);
        files.push({ path: fullPath, blob: { path: blobPath, size: stat.size } });
      } catch {
        // broken symlink or inaccessible
      }
    }
  }
}

// Scan a HF cache repo directory directly, bypassing the library.
// Picks the most recently modified snapshot and collects all files from it.
// Used as a fallback when scanCacheDir throws (e.g. stale ref pointing to
// a commit hash with no local snapshot).
async function scanRepoFallback(repoPath: string): Promise<{
  repoId: string; repoType: string; files: { path: string; blob: { path: string; size: number } }[];
  modified: Date;
} | null> {
  const name = repoPath.split('/').pop() ?? '';
  const sep = '--';
  const idx = name.indexOf(sep);
  if (idx < 0) return null;
  const typeStr = name.slice(0, idx);
  if (typeStr !== 'models') return null;
  const repoId = name.slice(idx + sep.length).replace(/--/g, '/');

  const snapshotsPath = repoPath + '/snapshots';
  if (!(await dirExists(snapshotsPath))) return null;

  let bestSnap = '';
  let bestMtime = 0;
  try {
    for await (const e of Deno.readDir(snapshotsPath)) {
      if (!e.isDirectory) continue;
      const s = await Deno.stat(snapshotsPath + '/' + e.name);
      const mt = s.mtime?.getTime() ?? 0;
      if (mt >= bestMtime) { bestMtime = mt; bestSnap = e.name; }
    }
  } catch { return null; }
  if (!bestSnap) return null;

  // deno-lint-ignore no-explicit-any
  const files: any[] = [];
  await walkDir(snapshotsPath + '/' + bestSnap, files, new Set());
  if (files.length === 0) return null;

  return { repoId, repoType: 'model', files, modified: new Date(bestMtime) };
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

  const groupedItems = new Map<string, RawItem[]>();
  for (const item of rawItems) {
    const shard = parseGgufShardInfo(item.name);
    const group = groupedItems.get(shard.logicalName) ?? [];
    group.push(item);
    groupedItems.set(shard.logicalName, group);
  }

  return Promise.all(Array.from(groupedItems.entries()).map(async ([logicalName, group]) => {
    const sortedGroup = [...group].sort((a, b) => compareGgufShardNames(a.name, b.name));
    const primary = sortedGroup[0];
    const details = await resolveGgufDetails(primary.filePath, logicalName);
    return {
      repo: logicalName.replace(/\.gguf$/i, ''),
      path: primary.filePath,
      size: sortedGroup.reduce((sum, item) => sum + item.size, 0),
      modified: sortedGroup.reduce(
        (latest, item) => item.mtime.getTime() > latest.getTime() ? item.mtime : latest,
        primary.mtime,
      ),
      files: sortedGroup.map(({ name, size }) => ({ name, size })),
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

    const snapshotPath: string | undefined = latest.path;
    if (snapshotPath) {
      // deno-lint-ignore no-explicit-any
      const knownBlobs = new Set<string>(allFiles.map((f: any) => f.blob?.path).filter(Boolean));
      await walkDir(snapshotPath, allFiles, knownBlobs);
    }

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
      const metadataCandidate = [...ggufFiles]
        .filter(f => !f.fileName.toLowerCase().includes('mmproj'))
        .sort((a, b) => compareGgufShardNames(a.fileName, b.fileName))[0] ?? ggufFiles[0];
      const shardInfo = parseGgufShardInfo(metadataCandidate.fileName);
      if (metadataCandidate.blobPath) {
        details = await resolveGgufDetails(metadataCandidate.blobPath, shardInfo.logicalName);
      } else {
        const quantization = parseGGUFQuantLabel(shardInfo.logicalName) ?? undefined;
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

  // Collect repo paths the library returned so we can find ones it dropped.
  // deno-lint-ignore no-explicit-any
  const knownRepoPaths = new Set(Array.from(cacheInfo.repos).map((r: any) => r.path ?? r.repoPath));

  // Scan the hub dir for model repos the library missed (e.g. stale refs
  // pointing to a commit hash with no local snapshot cause it to throw).
  const hubDir = hfCache + '/hub';
  const rescuedRepos: Promise<HfRepoInfo | null>[] = [];
  try {
    for await (const entry of Deno.readDir(hubDir)) {
      if (!entry.isDirectory || !entry.name.startsWith('models--')) continue;
      const fullPath = hubDir + '/' + entry.name;
      if (knownRepoPaths.has(fullPath)) continue;
      rescuedRepos.push(
        scanRepoFallback(fullPath).then(r => r ? processRepo({
          id: { name: r.repoId, type: r.repoType },
          path: fullPath,
          size: r.files.reduce((s, f) => s + (f.blob?.size ?? 0), 0),
          revisions: [{ files: r.files, lastModifiedAt: r.modified, path: '' }],
        }) : null)
      );
    }
  } catch { /* hub dir unreadable — already handled above */ }

  const [repoResults, rescued, looseGgufs, ggufSubdir] = await Promise.all([
    Promise.all(Array.from(cacheInfo.repos).map(processRepo)),
    Promise.all(rescuedRepos),
    scanLooseGgufs(hfCache),
    scanLooseGgufs(hfCache + '/gguf'),
  ]);

  const results: HfRepoInfo[] = [
    ...(repoResults.filter((r): r is HfRepoInfo => r !== null)),
    ...(rescued.filter((r): r is HfRepoInfo => r !== null)),
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
  let removed = false;
  for (const looseDir of [hfCache, `${hfCache}/gguf`]) {
    try {
      for await (const entry of Deno.readDir(looseDir)) {
        if (!entry.isFile || !entry.name.endsWith('.gguf')) continue;
        if (parseGgufShardInfo(entry.name).logicalStem !== baseName) continue;
        await Deno.remove(`${looseDir}/${entry.name}`);
        removed = true;
      }
    } catch {
      // not found, try next
    }
  }

  return removed;
}
