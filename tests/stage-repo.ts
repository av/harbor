/// <reference lib="deno.ns" />
// Materialize a bounded Harbor tree for matrix test rows.
//
// Rows must never bind-mount the developer's working tree. Only paths returned
// by `git ls-files` are copied — untracked and gitignored local blobs stay out.

function parentDir(path: string): string {
  const i = path.lastIndexOf("/");
  return i <= 0 ? "/" : path.slice(0, i);
}

/** Hard cap on staged artifact size (tracked tree is ~tens of MB today). */
export const STAGED_REPO_MAX_BYTES = 500 * 1024 * 1024;

/** Reserve per concurrent row: install copy + nested docker scratch. */
const PER_ROW_OVERHEAD_BYTES = 512 * 1024 * 1024;

/** Minimum free headroom after accounting for concurrent rows. */
const DISK_SAFETY_MARGIN_BYTES = 2 * 1024 * 1024 * 1024;

export type StagedRepoStats = {
  fileCount: number;
  totalBytes: number;
  destDir: string;
};

export const HEAVY_SUITE_DEFAULTS: Record<
  string,
  { distros: string[]; jobs: number }
> = {
  "boost-agentic-smoke": { distros: ["fedora-43"], jobs: 1 },
};

type CmdResult = { code: number; stdout: string; stderr: string };

async function run(
  cmd: string[],
  opts: { cwd?: string; silent?: boolean } = {},
): Promise<CmdResult> {
  const proc = new Deno.Command(cmd[0], {
    args: cmd.slice(1),
    cwd: opts.cwd,
    stdout: "piped",
    stderr: "piped",
  });
  const { code, stdout, stderr } = await proc.output();
  return {
    code,
    stdout: new TextDecoder().decode(stdout),
    stderr: new TextDecoder().decode(stderr),
  };
}

async function copyTrackedEntry(
  repoRoot: string,
  rel: string,
  destDir: string,
): Promise<number> {
  const src = `${repoRoot}/${rel}`;
  const dst = `${destDir}/${rel}`;
  let info: Deno.FileInfo;
  try {
    info = await Deno.lstat(src);
  } catch (e) {
    if (e instanceof Deno.errors.NotFound) {
      // Index lists a path the working tree no longer has — skip quietly.
      return 0;
    }
    throw e;
  }

  if (info.isSymlink) {
    const target = await Deno.readLink(src);
    await Deno.mkdir(parentDir(dst), { recursive: true });
    try {
      await Deno.symlink(target, dst);
    } catch (e) {
      if (e instanceof Deno.errors.AlreadyExists) {
        await Deno.remove(dst);
        await Deno.symlink(target, dst);
      } else {
        throw e;
      }
    }
    return 0;
  }

  if (!info.isFile) {
    return 0;
  }

  await Deno.mkdir(parentDir(dst), { recursive: true });
  await Deno.copyFile(src, dst);
  return info.size ?? 0;
}

/**
 * Copy exactly the git-index file list from `repoRoot` into `destDir`.
 * Uses working-tree bytes for tracked files (includes unstaged edits to tracked
 * paths) and never sees untracked/gitignored blobs.
 */
export async function materializeTrackedRepo(
  repoRoot: string,
  destDir: string,
): Promise<StagedRepoStats> {
  const git = await run(["git", "rev-parse", "--show-toplevel"], {
    cwd: repoRoot,
    silent: true,
  });
  if (git.code !== 0) {
    throw new Error(
      `materializeTrackedRepo: not a git repository (${git.stderr.trim()})`,
    );
  }
  const top = git.stdout.trim().replace(/\/+$/, "");
  const root = repoRoot.replace(/\/+$/, "");
  if (top !== root) {
    throw new Error(
      `materializeTrackedRepo: repo root mismatch (cwd=${repoRoot}, git=${top})`,
    );
  }

  const ls = await run(["git", "ls-files", "-z"], { cwd: repoRoot, silent: true });
  if (ls.code !== 0) {
    throw new Error(`git ls-files failed: ${ls.stderr.trim()}`);
  }

  await Deno.mkdir(destDir, { recursive: true });

  let fileCount = 0;
  let totalBytes = 0;
  const paths = ls.stdout.split("\0").filter(Boolean);

  for (const rel of paths) {
    const added = await copyTrackedEntry(repoRoot, rel, destDir);
    fileCount += 1;
    totalBytes += added;
    if (totalBytes > STAGED_REPO_MAX_BYTES) {
      throw new Error(
        `staged repo exceeds cap (${totalBytes} > ${STAGED_REPO_MAX_BYTES} bytes) — ` +
          `refusing to mount an oversized artifact`,
      );
    }
  }

  return { fileCount, totalBytes, destDir };
}

export async function freeBytesAt(path: string): Promise<number> {
  const parent = path.replace(/\/+$/, "") || "/";
  const r = await run(["df", "-B1", parent], { silent: true });
  if (r.code !== 0) {
    throw new Error(`df failed for ${parent}: ${r.stderr.trim()}`);
  }
  const line = r.stdout.trim().split("\n").at(-1) ?? "";
  const avail = line.split(/\s+/).at(3);
  if (!avail || !/^\d+$/.test(avail)) {
    throw new Error(`could not parse df output for ${parent}: ${line}`);
  }
  return Number(avail);
}

/**
 * Refuse to start a matrix run that would likely fill the filesystem.
 * `jobs` bounds concurrent rows; each may copy the staged tree during install.
 */
export async function assertDiskHeadroom(
  artifactsDir: string,
  jobs: number,
  stagedBytes: number,
): Promise<void> {
  const concurrent = Math.max(1, jobs);
  const estimated =
    stagedBytes * 2 * concurrent +
    PER_ROW_OVERHEAD_BYTES * concurrent +
    DISK_SAFETY_MARGIN_BYTES;
  const free = await freeBytesAt(artifactsDir);
  if (free < estimated) {
    const needGiB = (estimated / (1024 ** 3)).toFixed(1);
    const freeGiB = (free / (1024 ** 3)).toFixed(1);
    throw new Error(
      `insufficient disk for test matrix (free ${freeGiB} GiB, need ~${needGiB} GiB ` +
        `for ${concurrent} concurrent row(s) and a ${(stagedBytes / (1024 ** 2)).toFixed(0)} MiB staged repo). ` +
        `Reduce --jobs, pass --distros to run fewer rows, or free disk space.`,
    );
  }
}

export function applyHeavySuiteDefaults(
  args: {
    suites: string[] | null;
    distros: string[] | null;
    jobs: number;
  },
  rawArgv: string[],
  discoveredSuiteShorts: string[],
): void {
  const userSetDistros = rawArgv.some((a) =>
    a === "--distro" || a === "--distros" || a.startsWith("--distro=") ||
    a.startsWith("--distros=")
  );
  const userSetJobs = rawArgv.some((a) =>
    a === "--jobs" || a.startsWith("--jobs=")
  );

  const selected = args.suites ?? discoveredSuiteShorts;
  for (const short of selected) {
    const defaults = HEAVY_SUITE_DEFAULTS[short];
    if (!defaults) continue;
    if (!userSetDistros && args.distros === null) {
      args.distros = [...defaults.distros];
    }
    if (!userSetJobs) {
      args.jobs = Math.min(args.jobs, defaults.jobs);
    }
  }
}