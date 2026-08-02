/// <reference lib="deno.ns" />

import {
  HEAVY_SUITE_DEFAULTS,
  materializeTrackedRepo,
  resolveSuitePlan,
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

const ALL_ROWS = [
  "alpine-3",
  "archlinux",
  "debian-12",
  "fedora-43",
  "rocky-9",
  "ubuntu-2204",
  "ubuntu-2404",
];

Deno.test("resolveSuitePlan pins heavy-only selection to its defaults", () => {
  const plan = resolveSuitePlan(
    {
      suiteShorts: ["boost-agentic-smoke"],
      allRows: ALL_ROWS,
      distros: null,
      jobs: 4,
    },
    ["--suite", "boost-agentic-smoke"],
  );
  const expected = HEAVY_SUITE_DEFAULTS["boost-agentic-smoke"];
  if (JSON.stringify(plan.rows) !== JSON.stringify(expected.distros)) {
    throw new Error(`rows not pinned: ${plan.rows}`);
  }
  if (plan.jobs !== 1) {
    throw new Error(`jobs not capped to 1: ${plan.jobs}`);
  }
});

Deno.test("resolveSuitePlan resolves distros per suite for mixed selections", () => {
  const plan = resolveSuitePlan(
    {
      suiteShorts: ["install", "defaults-up"],
      allRows: ALL_ROWS,
      distros: null,
      jobs: 4,
    },
    ["--suite", "install,defaults-up"],
  );
  // Light suite keeps the full default row list.
  if (JSON.stringify(plan.suiteDistros.get("install")) !== JSON.stringify(ALL_ROWS)) {
    throw new Error(`install narrowed by heavy pin: ${plan.suiteDistros.get("install")}`);
  }
  // Heavy suite keeps its pin.
  const expected = HEAVY_SUITE_DEFAULTS["defaults-up"];
  if (
    JSON.stringify(plan.suiteDistros.get("defaults-up")) !==
      JSON.stringify(expected.distros)
  ) {
    throw new Error(`defaults-up not pinned: ${plan.suiteDistros.get("defaults-up")}`);
  }
  // Union of rows equals the full list; heavy jobs cap still applies.
  if (JSON.stringify(plan.rows) !== JSON.stringify(ALL_ROWS)) {
    throw new Error(`row union wrong: ${plan.rows}`);
  }
  if (plan.jobs !== 1) {
    throw new Error(`jobs not capped by heavy suite: ${plan.jobs}`);
  }
});

Deno.test("resolveSuitePlan respects explicit --distros and --jobs", () => {
  const withDistros = resolveSuitePlan(
    {
      suiteShorts: ["install", "boost-agentic-smoke"],
      allRows: ALL_ROWS,
      distros: ["ubuntu-2404"],
      jobs: 4,
    },
    ["--distros", "ubuntu-2404"],
  );
  if (JSON.stringify(withDistros.rows) !== JSON.stringify(["ubuntu-2404"])) {
    throw new Error(`explicit --distros not honored: ${withDistros.rows}`);
  }
  if (
    JSON.stringify(withDistros.suiteDistros.get("boost-agentic-smoke")) !==
      JSON.stringify(["ubuntu-2404"])
  ) {
    throw new Error("explicit --distros must override heavy pins");
  }
  if (withDistros.jobs !== 1) {
    throw new Error(`jobs should still cap to 1: ${withDistros.jobs}`);
  }

  const withJobs = resolveSuitePlan(
    {
      suiteShorts: ["boost-agentic-smoke"],
      allRows: ALL_ROWS,
      distros: null,
      jobs: 3,
    },
    ["--jobs", "3"],
  );
  if (withJobs.jobs !== 3) {
    throw new Error(`jobs should stay 3 when user passes --jobs: ${withJobs.jobs}`);
  }
  if (JSON.stringify(withJobs.rows) !== JSON.stringify(["fedora-43"])) {
    throw new Error(`distros should default when only --jobs set: ${withJobs.rows}`);
  }
});