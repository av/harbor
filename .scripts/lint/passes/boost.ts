/// <reference lib="deno.ns" />
/// <reference lib="dom" />

// Boost module integrity pass.
//
// Catches zero-byte `.py` module files under the Boost load paths. A truncated
// save during an agent session can leave a module empty while the filename
// still exists — Boost then fails to import it at runtime with a confusing
// stack trace. This pass surfaces that corruption at lint time.

import { join } from "https://deno.land/std/path/mod.ts";

import type { Finding } from "../types.ts";
import { collectFiles, relative } from "../util.ts";

export const HARBOR011 = "HARBOR011";

const BOOST_GLOBS = [
  "services/boost/src/modules/**/*.py",
  "services/boost/src/custom_modules/**/*.py",
];

const BOOST_EXCLUDES = [
  // Self-test fixtures intentionally include a zero-byte fail case.
  ".scripts/lint/fixtures/boost/**/*.py",
];

export interface BoostOptions {
  root: string;
  fileFilter?: string[] | null;
  globs?: string[];
  exclude?: string[];
}

export async function runBoost(opts: BoostOptions): Promise<Finding[]> {
  const globs = opts.globs ?? BOOST_GLOBS;
  const excludeGlobs = opts.exclude ?? BOOST_EXCLUDES;
  const files = await collectFiles(opts.root, globs, []);
  if (opts.fileFilter) {
    const seen = new Set(files);
    for (const rel of opts.fileFilter) {
      const abs = rel.startsWith("/") ? rel : join(opts.root, rel);
      if (seen.has(abs)) continue;
      try {
        const st = await Deno.stat(abs);
        if (st.isFile) {
          seen.add(abs);
          files.push(abs);
        }
      } catch {
        // Ignore missing explicit paths — other passes behave the same way.
      }
    }
    files.sort();
  }
  const drop = new Set<string>();
  if (!opts.fileFilter) {
    for (const excluded of await collectFiles(opts.root, excludeGlobs, [])) {
      drop.add(excluded);
    }
  }
  const findings: Finding[] = [];

  for (const abs of files) {
    const rel = relative(opts.root, abs);
    if (opts.fileFilter) {
      // Honour an explicit --files list even when the path lives under the
      // fixture exclude set — mirrors the bash pass self-test contract.
      if (!opts.fileFilter.includes(rel)) continue;
    } else if (drop.has(abs)) {
      continue;
    }

    const base = rel.split("/").pop() ?? rel;
    if (base === "__init__.py") continue;

    let size: number;
    try {
      size = (await Deno.stat(abs)).size;
    } catch {
      continue;
    }
    if (size !== 0) continue;

    findings.push({
      file: rel,
      pass: "boost",
      rule: HARBOR011,
      severity: "error",
      message:
        "zero-byte-boost-module: Boost module file is empty (0 bytes). " +
        "A truncated write during editing can leave the module importable by " +
        "name but with no implementation — restore from git or rewrite the module.",
      fix:
        "Restore the file from version control (e.g. `git checkout -- <path>`) " +
        "or recreate the module body. Re-run `harbor dev lint --boost` to verify.",
    });
  }

  return findings;
}