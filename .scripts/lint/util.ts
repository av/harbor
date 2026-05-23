/// <reference lib="deno.ns" />
/// <reference lib="dom" />

// Shared helpers used by more than one lint pass. Keep this tiny — single
// implementations of cross-cutting concerns (file globbing, path relativisation)
// so all three passes behave identically.

import { expandGlob } from "https://deno.land/std/fs/mod.ts";

// Expand `globs` from `root`, then drop any path matched by `exclude`.
// Returns absolute paths, sorted, deduplicated. Directories are skipped.
export async function collectFiles(
  root: string,
  globs: string[],
  exclude: string[] = [],
): Promise<string[]> {
  const seen = new Set<string>();
  for (const g of globs) {
    for await (
      const entry of expandGlob(g, { root, includeDirs: false, globstar: true })
    ) {
      if (entry.isFile) seen.add(entry.path);
    }
  }
  const drop = new Set<string>();
  for (const g of exclude) {
    for await (
      const entry of expandGlob(g, { root, includeDirs: false, globstar: true })
    ) {
      if (entry.isFile) drop.add(entry.path);
    }
  }
  return [...seen].filter((p) => !drop.has(p)).sort();
}

// Turn an absolute path into a repo-relative path when possible. Falls back
// to the input untouched when the path does not live under `root`.
export function relative(root: string, p: string): string {
  return p.startsWith(root + "/") ? p.slice(root.length + 1) : p;
}
