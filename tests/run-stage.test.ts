/// <reference lib="deno.ns" />

import {
  applyHeavySuiteDefaults,
  HEAVY_SUITE_DEFAULTS,
  materializeTrackedRepo,
  STAGED_REPO_MAX_BYTES,
} from "./stage-repo.ts";

const REPO_ROOT = new URL("..", import.meta.url).pathname.replace(/\/+$/, "");

Deno.test("materializeTrackedRepo copies only git-tracked files", async () => {
  const tmp = await Deno.makeTempDir({ prefix: "harbor-stage-" });
  try {
    const stats = await materializeTrackedRepo(REPO_ROOT, `${tmp}/staged`);
    if (stats.fileCount < 100) {
      throw new Error(`expected hundreds of tracked files, got ${stats.fileCount}`);
    }
    if (stats.totalBytes > STAGED_REPO_MAX_BYTES) {
      throw new Error(`staged repo exceeds cap: ${stats.totalBytes}`);
    }
    // harbor.sh is tracked and required by install suites.
    const harborSh = `${tmp}/staged/harbor.sh`;
    const info = await Deno.stat(harborSh);
    if (!info.isFile) throw new Error("harbor.sh missing from staged artifact");
  } finally {
    await Deno.remove(tmp, { recursive: true });
  }
});

Deno.test("run.ts does not bind-mount REPO_ROOT into containers", async () => {
  const src = await Deno.readTextFile(`${REPO_ROOT}/tests/run.ts`);
  if (src.includes("${REPO_ROOT}:/opt/harbor-test/repo")) {
    throw new Error("run.ts still bind-mounts REPO_ROOT — must mount stagedRepoDir only");
  }
  if (src.includes("tar -C /opt/harbor-test/repo")) {
    throw new Error("run.ts still bulk-copies repo inside containers");
  }
});

Deno.test("applyHeavySuiteDefaults pins boost-agentic-smoke matrix", () => {
  const args = {
    suites: ["boost-agentic-smoke"],
    distros: null as string[] | null,
    jobs: 4,
  };
  applyHeavySuiteDefaults(args, ["--suite", "boost-agentic-smoke"], [
    "install",
    "boost-agentic-smoke",
  ]);
  const expected = HEAVY_SUITE_DEFAULTS["boost-agentic-smoke"];
  if (JSON.stringify(args.distros) !== JSON.stringify(expected.distros)) {
    throw new Error(`distros not defaulted: ${args.distros}`);
  }
  if (args.jobs !== 1) {
    throw new Error(`jobs not capped to 1: ${args.jobs}`);
  }
});

Deno.test("applyHeavySuiteDefaults respects explicit --distros and --jobs", () => {
  const withDistros = {
    suites: ["boost-agentic-smoke"],
    distros: ["ubuntu-2404"] as string[] | null,
    jobs: 4,
  };
  applyHeavySuiteDefaults(withDistros, ["--distros", "ubuntu-2404"], [
    "boost-agentic-smoke",
  ]);
  if (withDistros.distros?.[0] !== "ubuntu-2404") {
    throw new Error("distros should not be overridden when user passes --distros");
  }
  if (withDistros.jobs !== 1) {
    throw new Error(`jobs should still cap to 1: ${withDistros.jobs}`);
  }

  const withJobs = {
    suites: ["boost-agentic-smoke"],
    distros: null as string[] | null,
    jobs: 3,
  };
  applyHeavySuiteDefaults(withJobs, ["--jobs", "3"], ["boost-agentic-smoke"]);
  if (withJobs.jobs !== 3) {
    throw new Error(`jobs should stay 3 when user passes --jobs: ${withJobs.jobs}`);
  }
  if (JSON.stringify(withJobs.distros) !== JSON.stringify(["fedora-43"])) {
    throw new Error(`distros should default when only --jobs set: ${withJobs.distros}`);
  }
});