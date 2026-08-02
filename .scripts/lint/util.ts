/// <reference lib="deno.ns" />
/// <reference lib="dom" />

// Shared helpers used by more than one lint pass. Keep this tiny — single
// implementations of cross-cutting concerns (file globbing, path relativisation)
// so all three passes behave identically.

import { globToRegExp, join } from "https://deno.land/std/path/mod.ts";

// Service runtime data (e.g. services/daytona/data) can contain root-owned
// dirs that throw PermissionDenied when walked — skipping them is a
// performance optimisation, not a correctness requirement: safeGlob below
// survives unreadable/vanishing entries regardless of this list.
// netdata's workspace defaults to ./services/netdata itself, so its runtime
// dirs (cache/lib) are listed explicitly.
export const RUNTIME_DIR_EXCLUDES = [
  "services/*/data",
  "services/*/db",
  "services/*/storage",
  "services/*/workspace",
  "services/*/vectordb",
  "services/*/meili_data*",
  // comfyui's workspace bind-mounts the container's /root (see compose.comfyui.yml).
  "services/comfyui/root",
  // Runtime caches (mcp's npx locks vanish mid-walk, windmill vendors
  // whole language runtimes, lemonade vendors third-party shell scripts).
  "services/*/cache",
  "services/netdata/lib",
  // morphic's db volumes are root-owned bind mounts (see compose.morphic.yml).
  "services/morphic/postgres",
  "services/morphic/redis",
  // dify keeps its runtime volumes at the repo root (see compose.dify.yml).
  "dify/volumes",
];

const GLOB_CHARS = /[*?[\]{}]/;
const GLOB_OPTS = { globstar: true, extended: true } as const;

// Longest leading path prefix of `pattern` with no glob metacharacters —
// the deepest directory we can start walking from.
function staticPrefix(pattern: string): string {
  const out: string[] = [];
  for (const seg of pattern.split("/")) {
    if (GLOB_CHARS.test(seg)) break;
    out.push(seg);
  }
  return out.join("/") || "/";
}

function isTransientFsError(err: unknown): boolean {
  return err instanceof Deno.errors.PermissionDenied ||
    err instanceof Deno.errors.NotFound ||
    err instanceof Deno.errors.NotADirectory;
}

export interface GlobEntry {
  path: string;
  isFile: true;
}

// Crash-proof replacement for std's expandGlob: walks the filesystem itself
// and silently skips any directory or entry that is unreadable
// (PermissionDenied) or vanishes mid-walk (NotFound). Root-owned service
// runtime dirs must never be able to break `harbor dev lint`.
// Yields matching regular files only; symlinks are not followed (matching
// the previous expandGlob followSymlinks:false behaviour).
// `exclude` patterns prune whole directories and drop matching files.
export async function* safeGlob(
  glob: string,
  opts: { root: string; exclude?: string[] },
): AsyncGenerator<GlobEntry> {
  const exclude = opts.exclude ?? RUNTIME_DIR_EXCLUDES;
  const pattern = glob.startsWith("/") ? glob : join(opts.root, glob);
  const re = globToRegExp(pattern, GLOB_OPTS);
  const excludeRes = exclude.map((e) =>
    globToRegExp(e.startsWith("/") ? e : join(opts.root, e), GLOB_OPTS)
  );
  const base = staticPrefix(pattern);

  let baseInfo: Deno.FileInfo;
  try {
    baseInfo = await Deno.lstat(base);
  } catch {
    return;
  }
  if (baseInfo.isFile) {
    if (re.test(base) && !excludeRes.some((r) => r.test(base))) {
      yield { path: base, isFile: true };
    }
    return;
  }
  if (!baseInfo.isDirectory) return;

  async function* walk(dir: string): AsyncGenerator<GlobEntry> {
    const entries: Deno.DirEntry[] = [];
    try {
      for await (const e of Deno.readDir(dir)) entries.push(e);
    } catch (err) {
      if (isTransientFsError(err)) return;
      throw err;
    }
    for (const e of entries) {
      const p = join(dir, e.name);
      if (e.isDirectory) {
        if (excludeRes.some((r) => r.test(p))) continue;
        yield* walk(p);
      } else if (e.isFile) {
        if (!re.test(p)) continue;
        if (excludeRes.some((r) => r.test(p))) continue;
        yield { path: p, isFile: true };
      }
      // Symlinks and other entry types are skipped, as before.
    }
  }

  yield* walk(base);
}

// Expand `globs` from `root`, then drop any path matched by `exclude`.
// Returns absolute paths, sorted, deduplicated. Directories are skipped.
export async function collectFiles(
  root: string,
  globs: string[],
  exclude: string[] = [],
): Promise<string[]> {
  const seen = new Set<string>();
  for (const g of globs) {
    for await (const entry of safeGlob(g, { root })) {
      seen.add(entry.path);
    }
  }
  const drop = new Set<string>();
  for (const g of exclude) {
    for await (const entry of safeGlob(g, { root })) {
      drop.add(entry.path);
    }
  }
  return [...seen].filter((p) => !drop.has(p)).sort();
}

// Turn an absolute path into a repo-relative path when possible. Falls back
// to the input untouched when the path does not live under `root`.
export function relative(root: string, p: string): string {
  return p.startsWith(root + "/") ? p.slice(root.length + 1) : p;
}
