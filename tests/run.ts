/// <reference lib="deno.ns" />
/// <reference lib="dom" />

// Harbor test orchestrator.
//
// Each (row, suite) pair is one observation:
//   row   = a Containerfile under tests/containers/
//   suite = a bash script under tests/suites/
//
// Rows run in parallel (bounded by --jobs). Within a row, suites run
// sequentially — 02-smoke assumes 01-install already left `harbor` on PATH.
//
// The runner is self-contained: it probes the host, builds row images,
// launches privileged systemd containers, waits for the nested dockerd,
// execs each suite, captures stdout/stderr live to both tty and a per-suite
// logfile on the host, then tears down. Exit 0 iff every observation passes.

// ── Arg parsing ──────────────────────────────────────────────────────────────

type Args = {
  suites: string[] | null; // null = all
  distros: string[] | null; // null = all
  keep: boolean;
  rebuild: boolean;
  runtime: string | null; // null = autodetect
  installSource: "local" | "github";
  jobs: number;
  json: boolean;
  // Per-row wall-time budget. When exceeded, the orchestrator SIGKILLs the
  // row container; any in-flight suite is marked "killed" (distinct from
  // "fail") and remaining suites for that row are also marked killed.
  // 0 disables the budget.
  timeoutSeconds: number;
  help: boolean;
};

function defaultJobs(): number {
  const cores = navigator.hardwareConcurrency || 2;
  return Math.max(1, Math.floor(cores / 2));
}

function parseArgs(raw: string[]): Args {
  const args: Args = {
    suites: null,
    distros: null,
    keep: false,
    rebuild: false,
    runtime: null,
    // Spec default (hardening.md line 104): github exercises the published
    // release artefact, which is what nightly coverage actually wants. CI on
    // PRs overrides to --install-source local so the working tree under
    // review is what's tested; see .github/workflows/test.yml.
    installSource: "github",
    jobs: defaultJobs(),
    json: false,
    // 1800s per row accommodates first-run image builds + the full suite set
    // on the slowest distro (fedora-43 routinely ~10m for install+smoke).
    // Override via --timeout. 0 disables.
    timeoutSeconds: 1800,
    help: false,
  };

  const takeValue = (i: number, inline: string | undefined, key: string): [string, number] => {
    if (inline !== undefined) return [inline, i];
    const next = raw[i + 1];
    if (next === undefined || next.startsWith("--")) {
      throw new Error(`Missing value for --${key}`);
    }
    return [next, i + 1];
  };

  for (let i = 0; i < raw.length; i++) {
    const arg = raw[i];
    if (!arg.startsWith("--")) {
      throw new Error(`Unexpected positional argument: ${arg}`);
    }
    const [rawKey, inline] = arg.slice(2).split("=", 2) as [string, string | undefined];
    switch (rawKey) {
      case "help":
      case "h":
        args.help = true;
        break;
      case "keep":
        args.keep = true;
        break;
      case "rebuild":
        args.rebuild = true;
        break;
      case "json":
        args.json = true;
        break;
      case "suite":
      case "suites": {
        const [v, ni] = takeValue(i, inline, rawKey);
        args.suites = v.split(",").map((s) => s.trim()).filter(Boolean);
        i = ni;
        break;
      }
      case "distro":
      case "distros": {
        const [v, ni] = takeValue(i, inline, rawKey);
        args.distros = v.split(",").map((s) => s.trim()).filter(Boolean);
        i = ni;
        break;
      }
      case "runtime": {
        const [v, ni] = takeValue(i, inline, rawKey);
        if (v !== "docker" && v !== "podman") {
          throw new Error(`--runtime must be "docker" or "podman" (got "${v}")`);
        }
        args.runtime = v;
        i = ni;
        break;
      }
      case "install-source": {
        const [v, ni] = takeValue(i, inline, rawKey);
        if (v !== "local" && v !== "github") {
          throw new Error(`--install-source must be "local" or "github" (got "${v}")`);
        }
        args.installSource = v;
        i = ni;
        break;
      }
      case "jobs": {
        const [v, ni] = takeValue(i, inline, rawKey);
        const n = Number.parseInt(v, 10);
        if (!Number.isFinite(n) || n < 1) {
          throw new Error(`--jobs must be a positive integer (got "${v}")`);
        }
        args.jobs = n;
        i = ni;
        break;
      }
      case "timeout": {
        const [v, ni] = takeValue(i, inline, rawKey);
        const n = Number.parseInt(v, 10);
        if (!Number.isFinite(n) || n < 0) {
          throw new Error(`--timeout must be a non-negative integer (got "${v}")`);
        }
        args.timeoutSeconds = n;
        i = ni;
        break;
      }
      default:
        throw new Error(`Unknown argument: --${rawKey}`);
    }
  }
  return args;
}

function printHelp() {
  console.log(`Usage: harbor dev test [options]

Options:
  --suite, --suites <list>        Comma-separated suite names (e.g. install,smoke).
                                  Default: all suites.
  --distro, --distros <list>      Comma-separated row names (e.g. ubuntu-2404,fedora-43).
                                  Default: all rows.
  --keep                          Do not tear down containers after the run.
  --rebuild                       Force a rebuild of every selected row image.
  --runtime docker|podman         Override container runtime autodetection.
  --install-source local|github   Install source used by 01-install (default: github).
  --jobs <n>                      Max concurrent rows (default: cores/2).
  --timeout <s>                   Per-row wall-time budget in seconds (default: 1800,
                                  0 to disable). On expiry the row is SIGKILLed and
                                  remaining suites are marked 'killed'.
  --json                          Emit machine-readable JSON summary.
  --help                          Show this help.

Examples:
  harbor dev test
  harbor dev test --suite smoke
  harbor dev test --distros ubuntu-2404 --suite install,smoke
  harbor dev test --keep
  harbor dev test --json
`);
}

// ── Paths and identity ───────────────────────────────────────────────────────

const REPO_ROOT = Deno.cwd();
const TESTS_DIR = `${REPO_ROOT}/tests`;
const CONTAINERS_DIR = `${TESTS_DIR}/containers`;
const SUITES_DIR = `${TESTS_DIR}/suites`;
const ARTIFACTS_DIR = `${TESTS_DIR}/artifacts`;

function generateRunId(): string {
  const now = new Date();
  const ts = [
    now.getUTCFullYear().toString(),
    (now.getUTCMonth() + 1).toString().padStart(2, "0"),
    now.getUTCDate().toString().padStart(2, "0"),
    "-",
    now.getUTCHours().toString().padStart(2, "0"),
    now.getUTCMinutes().toString().padStart(2, "0"),
    now.getUTCSeconds().toString().padStart(2, "0"),
  ].join("");
  // crypto.getRandomValues is collision-safe across concurrent invocations
  // that land in the same UTC second; Math.random shared a PRNG per process
  // and could realistically repeat inside a tight orchestrator loop.
  const sha = crypto.getRandomValues(new Uint32Array(1))[0]
    .toString(16)
    .padStart(8, "0");
  return `${ts}-${sha}`;
}

// ── Shell primitives ─────────────────────────────────────────────────────────

type CmdResult = { code: number; stdout: string; stderr: string };

async function run(
  cmd: string[],
  opts: { silent?: boolean; env?: Record<string, string> } = {},
): Promise<CmdResult> {
  const proc = new Deno.Command(cmd[0], {
    args: cmd.slice(1),
    stdout: "piped",
    stderr: "piped",
    env: opts.env,
  });
  const { code, stdout, stderr } = await proc.output();
  const out = new TextDecoder().decode(stdout);
  const err = new TextDecoder().decode(stderr);
  if (!opts.silent) {
    // Progress echoes land on stderr so stdout stays reserved for --json output.
    const enc = new TextEncoder();
    if (out) Deno.stderr.writeSync(enc.encode(out));
    if (err) Deno.stderr.writeSync(enc.encode(err));
  }
  return { code, stdout: out, stderr: err };
}

// Run a child and stream both stdout and stderr to our own stderr. Keeping
// the child's stdout off our stdout matters for --json mode — docker build's
// progress prose would otherwise prepend itself to the JSON payload.
async function runInherit(cmd: string[]): Promise<number> {
  const proc = new Deno.Command(cmd[0], {
    args: cmd.slice(1),
    stdin: "null",
    stdout: "piped",
    stderr: "piped",
  }).spawn();
  const pipe = async (src: ReadableStream<Uint8Array>) => {
    const reader = src.getReader();
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        await Deno.stderr.write(value);
      }
    } finally {
      reader.releaseLock();
    }
  };
  const [{ code }] = await Promise.all([
    proc.status,
    pipe(proc.stdout),
    pipe(proc.stderr),
  ]);
  return code;
}

// Stream a child's merged stdout+stderr to both the controlling terminal
// (so the human sees live progress) and a file handle on disk (so we still
// have a log if the container is SIGKILL'd mid-stream). Returns the exit code.
async function runTeeToFile(cmd: string[], filePath: string, prefix: string): Promise<number> {
  const file = await Deno.open(filePath, { write: true, create: true, truncate: true });
  try {
    const proc = new Deno.Command(cmd[0], {
      args: cmd.slice(1),
      stdout: "piped",
      stderr: "piped",
      stdin: "null",
    }).spawn();
    const enc = new TextEncoder();
    const pipe = async (src: ReadableStream<Uint8Array>) => {
      const reader = src.getReader();
      const dec = new TextDecoder();
      let carry = "";
      try {
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          await file.write(value); // raw on disk — survives SIGKILL mid-stream.
          carry += dec.decode(value, { stream: true });
          const parts = carry.split("\n");
          carry = parts.pop() ?? "";
          // Live progress goes to stderr — keeps stdout reserved for the final
          // JSON payload when --json is active. The disk log still captures
          // every byte via the `file.write(value)` above.
          for (const line of parts) {
            await Deno.stderr.write(enc.encode(`${prefix}${line}\n`));
          }
        }
        if (carry.length > 0) {
          await Deno.stderr.write(enc.encode(`${prefix}${carry}`));
        }
      } finally {
        reader.releaseLock();
      }
    };
    const [{ code }] = await Promise.all([
      proc.status,
      pipe(proc.stdout),
      pipe(proc.stderr),
    ]);
    return code;
  } finally {
    file.close();
  }
}

// Progress output goes to stderr so `--json`'s stdout stream stays pure JSON.
// Keeping stderr as the channel in all modes means interactive runs still see
// the live status, while pipelines like `harbor dev test --json | tee run.json`
// can feed straight into a JSON parser without stripping prose.
function log(prefix: string, msg: string) {
  console.error(`[${prefix}] ${msg}`);
}

// ── Host probe ───────────────────────────────────────────────────────────────

type HostProbe = {
  os: "linux" | "darwin" | "other";
  runtime: string; // "docker" | "podman"
  runtimeKind: "docker" | "podman";
  selinuxEnforcing: boolean;
  rootless: boolean;
  mountFlag: string; // ":z" or ""
  securityLabelDisable: boolean;
};

async function probeHost(argRuntime: string | null): Promise<HostProbe> {
  const probe: HostProbe = {
    os: "other",
    runtime: "",
    runtimeKind: "docker",
    selinuxEnforcing: false,
    rootless: false,
    mountFlag: "",
    securityLabelDisable: false,
  };

  // Host OS
  const uname = await run(["uname", "-s"], { silent: true });
  const un = uname.stdout.trim();
  if (un === "Linux") probe.os = "linux";
  else if (un === "Darwin") probe.os = "darwin";

  // Runtime selection. When the user passes --runtime explicitly we still
  // verify the binary is on PATH before probing it — Deno.Command throws a
  // raw NotFound on missing executables, which surfaces to the user as an
  // unhandled promise rejection rather than an actionable message.
  if (argRuntime) {
    const w = await run(["bash", "-c", `command -v ${argRuntime}`], { silent: true });
    if (w.code !== 0) {
      const other = argRuntime === "docker" ? "podman" : "docker";
      throw new Error(
        `--runtime ${argRuntime} requested but '${argRuntime}' is not on PATH. ` +
          `Install it or try --runtime ${other}; omit --runtime to autodetect.`,
      );
    }
    probe.runtime = argRuntime;
  } else {
    for (const candidate of ["docker", "podman"]) {
      const w = await run(["bash", "-c", `command -v ${candidate}`], { silent: true });
      if (w.code === 0) {
        probe.runtime = candidate;
        break;
      }
    }
  }
  if (!probe.runtime) {
    throw new Error(
      "No container runtime found on PATH. Install Docker (https://docs.docker.com/engine/install/) " +
        "or Podman, then retry.",
    );
  }

  // Runtime kind
  const ver = await run([probe.runtime, "--version"], { silent: true });
  probe.runtimeKind = /podman/i.test(ver.stdout) ? "podman" : "docker";

  // Daemon reachable
  const info = await run([probe.runtime, "info"], { silent: true });
  if (info.code !== 0) {
    const hint = probe.os === "darwin"
      ? "open Docker Desktop"
      : "sudo systemctl start docker";
    throw new Error(
      `${probe.runtime} daemon is not reachable. Start it with: ${hint}`,
    );
  }

  // Rootless docker is incompatible with --privileged. Abort with a pointer.
  if (probe.runtimeKind === "docker") {
    const fmt = await run(
      [probe.runtime, "info", "--format", "{{.SecurityOptions}}"],
      { silent: true },
    );
    if (/name=rootless/.test(fmt.stdout)) {
      probe.rootless = true;
    }
  }

  if (probe.rootless) {
    throw new Error(
      "rootless docker cannot grant --privileged, which this runner requires for the " +
        "nested dockerd inside each row. Rerun with --runtime podman (rootless podman supports " +
        "this natively) or switch to rootful docker.",
    );
  }

  // SELinux — Linux only
  if (probe.os === "linux") {
    const se = await run(["bash", "-c", "getenforce 2>/dev/null || true"], { silent: true });
    probe.selinuxEnforcing = se.stdout.trim() === "Enforcing";
    if (probe.selinuxEnforcing) {
      probe.mountFlag = ":z";
      // podman labels per-container by default; --security-opt label=disable is a docker-only workaround.
      if (probe.runtimeKind === "docker") {
        probe.securityLabelDisable = true;
      }
    }
  }

  return probe;
}

// ── Row discovery ───────────────────────────────────────────────────────────

// base.Containerfile is the shared layer every row inherits from — it is not
// a row itself and must be excluded from matrix discovery.
const BASE_ROW_NAME = "base";

async function discoverRows(filter: string[] | null): Promise<string[]> {
  const entries: string[] = [];
  for await (const entry of Deno.readDir(CONTAINERS_DIR)) {
    if (entry.isFile && entry.name.endsWith(".Containerfile")) {
      const name = entry.name.replace(/\.Containerfile$/, "");
      if (name === BASE_ROW_NAME) continue;
      entries.push(name);
    }
  }
  entries.sort();
  if (!filter) return entries;
  const chosen = filter.filter((f) => entries.includes(f));
  const missing = filter.filter((f) => !entries.includes(f));
  if (missing.length > 0) {
    throw new Error(
      `Unknown row(s): ${missing.join(", ")}. Available: ${entries.join(", ")}.`,
    );
  }
  return chosen;
}

// ── Suite discovery ─────────────────────────────────────────────────────────

type Suite = { id: string; file: string; short: string };

async function discoverSuites(filter: string[] | null): Promise<Suite[]> {
  const all: Suite[] = [];
  for await (const entry of Deno.readDir(SUITES_DIR)) {
    if (entry.isFile && entry.name.endsWith(".sh")) {
      // 01-install.sh → { id: "01-install", short: "install" }
      const id = entry.name.replace(/\.sh$/, "");
      const short = id.replace(/^\d+-/, "");
      all.push({ id, file: entry.name, short });
    }
  }
  all.sort((a, b) => a.id.localeCompare(b.id));

  if (!filter) return all;
  const wanted = new Set(filter);
  const chosen = all.filter((s) => wanted.has(s.short) || wanted.has(s.id));
  const found = new Set(chosen.flatMap((s) => [s.short, s.id]));
  const missing = filter.filter((f) => !found.has(f));
  if (missing.length > 0) {
    throw new Error(
      `Unknown suite(s): ${missing.join(", ")}. Available: ${all.map((s) => s.short).join(", ")}.`,
    );
  }
  return chosen;
}

// ── Image build ─────────────────────────────────────────────────────────────

const IMAGE_PREFIX = "harbor-test";
// Label key on built images. Holds the sha256 of the inputs that produced
// the image. The skip-build check reads this label and rebuilds on mismatch
// — docker's own layer cache compares by RUN steps and would happily serve
// a stale image after a Containerfile edit if we trusted "tag exists" alone.
const HASH_LABEL = "harbor-test-hash";

function imageFor(row: string): string {
  return `${IMAGE_PREFIX}/${row}:latest`;
}

// Stable hex sha256 of an arbitrary byte slice. Used to fingerprint the
// build inputs of each row image; the result lands on the image as a label.
async function sha256Hex(data: Uint8Array): Promise<string> {
  // Copy into a fresh ArrayBuffer-backed view so the WebCrypto type system
  // accepts it (SharedArrayBuffer-backed Uint8Arrays are rejected by the
  // BufferSource constraint).
  const view = new Uint8Array(data.byteLength);
  view.set(data);
  const buf = await crypto.subtle.digest("SHA-256", view.buffer);
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

// Hash the inputs that determine an image's content. Everything that the
// `docker build` step actually sees: the row's Containerfile, the shared
// base.Containerfile, and the daemon.json that base.Containerfile bakes in.
// Suite scripts and lib helpers are bind-mounted at runtime — they are NOT
// baked into the image, so they must NOT contribute to the hash. (If that
// ever changes, this is the function to update.)
async function rowContentHash(row: string): Promise<string> {
  const inputs = [
    `${CONTAINERS_DIR}/${row}.Containerfile`,
    `${CONTAINERS_DIR}/${BASE_ROW_NAME}.Containerfile`,
    `${CONTAINERS_DIR}/daemon.json`,
  ];
  const enc = new TextEncoder();
  const parts: Uint8Array[] = [];
  for (const path of inputs) {
    parts.push(enc.encode(`# ${path}\n`));
    parts.push(await Deno.readFile(path));
    parts.push(enc.encode("\n"));
  }
  let total = 0;
  for (const p of parts) total += p.length;
  const concat = new Uint8Array(total);
  let off = 0;
  for (const p of parts) {
    concat.set(p, off);
    off += p.length;
  }
  return await sha256Hex(concat);
}

async function imageHashLabel(runtime: string, img: string): Promise<string | null> {
  // Returns the recorded harbor-test-hash label on a built image, or null
  // if the image is absent or has no such label (older builds, foreign
  // images that happened to use the same tag).
  const fmt = `{{index .Config.Labels "${HASH_LABEL}"}}`;
  const r = await run([runtime, "image", "inspect", img, "--format", fmt], { silent: true });
  if (r.code !== 0) return null;
  const v = r.stdout.trim();
  // Go templates render missing keys as the literal string "<no value>".
  if (!v || v === "<no value>") return null;
  return v;
}

// Build the shared base image (harbor-test/base:latest) first. Every row
// `FROM harbor-test/base AS harbor-base` then copies the shared daemon.json
// out of that stage — if the base image is missing, every row build fails
// with "harbor-test/base: pull access denied". Building it here before any
// row build fans out removes that failure mode.
async function buildBaseImage(runtime: string, rebuild: boolean): Promise<void> {
  const img = imageFor(BASE_ROW_NAME);
  // Hash inputs match rowContentHash: base.Containerfile + daemon.json.
  // The base image bakes in only the daemon.json and that file's source.
  const enc = new TextEncoder();
  const parts: Uint8Array[] = [];
  for (const path of [
    `${CONTAINERS_DIR}/${BASE_ROW_NAME}.Containerfile`,
    `${CONTAINERS_DIR}/daemon.json`,
  ]) {
    parts.push(enc.encode(`# ${path}\n`));
    parts.push(await Deno.readFile(path));
    parts.push(enc.encode("\n"));
  }
  let total = 0;
  for (const p of parts) total += p.length;
  const concat = new Uint8Array(total);
  let off = 0;
  for (const p of parts) {
    concat.set(p, off);
    off += p.length;
  }
  const wantHash = await sha256Hex(concat);

  if (!rebuild) {
    const have = await imageHashLabel(runtime, img);
    if (have === wantHash) {
      log("base", `image ${img} content-hash matches, skipping build (--rebuild to force)`);
      return;
    }
    if (have !== null && have !== wantHash) {
      log("base", `image ${img} content-hash drift (have=${have.slice(0, 12)} want=${wantHash.slice(0, 12)}), rebuilding`);
    }
  }
  log("base", `building ${img} (hash=${wantHash.slice(0, 12)})...`);
  const cmd = [
    runtime,
    "build",
    "--tag", img,
    "--label", `${HASH_LABEL}=${wantHash}`,
    "--file", `${CONTAINERS_DIR}/${BASE_ROW_NAME}.Containerfile`,
    CONTAINERS_DIR,
  ];
  const code = await runInherit(cmd);
  if (code !== 0) {
    throw new Error(`base: image build failed (${runtime} build exited ${code})`);
  }
}

async function buildRowImage(
  runtime: string,
  row: string,
  rebuild: boolean,
): Promise<void> {
  const img = imageFor(row);
  const wantHash = await rowContentHash(row);
  if (!rebuild) {
    const have = await imageHashLabel(runtime, img);
    if (have === wantHash) {
      log(row, `image ${img} content-hash matches, skipping build (--rebuild to force)`);
      return;
    }
    if (have !== null && have !== wantHash) {
      log(row, `image ${img} content-hash drift (have=${have.slice(0, 12)} want=${wantHash.slice(0, 12)}), rebuilding`);
    }
  }
  log(row, `building ${img} (hash=${wantHash.slice(0, 12)})...`);
  const cmd = [
    runtime,
    "build",
    "--tag", img,
    "--label", `${HASH_LABEL}=${wantHash}`,
    "--file", `${CONTAINERS_DIR}/${row}.Containerfile`,
    CONTAINERS_DIR,
  ];
  const code = await runInherit(cmd);
  if (code !== 0) {
    throw new Error(`${row}: image build failed (${runtime} build exited ${code})`);
  }
}

// ── Row lifecycle ───────────────────────────────────────────────────────────

type RunFlags = {
  containerName: string;
  image: string;
  hostArtifactsDir: string;
};

function rowContainerName(runId: string, row: string): string {
  // Keep it < 63 chars and DNS-safe — docker appends domain suffixes internally.
  return `harbor-test-${runId.slice(0, 15)}-${row}`;
}

function dockerRunArgs(
  probe: HostProbe,
  row: string,
  image: string,
  containerName: string,
  hostArtifactsDir: string,
): string[] {
  const flags: string[] = [
    probe.runtime,
    "run",
    "--detach",
    "--name", containerName,
    "--privileged",
    "--cgroupns=host",
    "--tmpfs", "/run",
    "--tmpfs", "/run/lock",
    "-v", "/sys/fs/cgroup:/sys/fs/cgroup:rw",
    "-v", `${REPO_ROOT}:/opt/harbor-test/repo${probe.mountFlag}`,
    "-v", `${hostArtifactsDir}:/opt/harbor-test/artifacts${probe.mountFlag}`,
  ];
  if (probe.securityLabelDisable) {
    flags.push("--security-opt", "label=disable");
  }
  flags.push(image);
  return flags;
}

async function waitForSystemReady(
  runtime: string,
  container: string,
  _row: string,
  isOpenRc: boolean,
): Promise<void> {
  // On systemd rows we wait for `is-system-running` to return {running,degraded}
  // — "degraded" is fine inside a container because we've intentionally pruned
  // some units (getty, networkd-wait). On OpenRC (alpine) we block on `rc`
  // reaching runlevel default. Both converge on "dockerd accepts commands".
  const deadline = Date.now() + 90_000;
  while (Date.now() < deadline) {
    const probe = isOpenRc
      ? await run(
          [runtime, "exec", container, "sh", "-c", "rc-status -r || true"],
          { silent: true },
        )
      : await run(
          [runtime, "exec", container, "systemctl", "is-system-running", "--wait"],
          { silent: true },
        );
    const out = (probe.stdout + probe.stderr).toLowerCase();
    if (isOpenRc) {
      if (out.includes("default")) return;
    } else {
      if (out.includes("running") || out.includes("degraded")) return;
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  // Fail loud instead of warning-and-continuing. If init never reached a ready
  // state, the nested docker wait is guaranteed to burn its own 60s timeout
  // (systemctl start docker has nothing to talk to), so we'd spend 150s total
  // before failing anyway. Abort now with a specific error the row summary
  // can surface verbatim.
  throw new Error(
    `${isOpenRc ? "openrc" : "systemd"} did not reach ready state within 90s — aborting row`,
  );
}

async function waitForInnerDocker(
  runtime: string,
  container: string,
  row: string,
  isOpenRc: boolean,
): Promise<void> {
  // Kick the daemon if it is not yet up. On systemd rows docker.service is
  // enabled at build time, but `systemctl start` is idempotent — we always
  // call it to cover the case of a disabled unit.
  if (isOpenRc) {
    await run([runtime, "exec", container, "rc-service", "docker", "start"], { silent: true });
  } else {
    await run([runtime, "exec", container, "systemctl", "start", "docker"], { silent: true });
  }
  const deadline = Date.now() + 60_000;
  while (Date.now() < deadline) {
    const probe = await run(
      [runtime, "exec", container, "docker", "info"],
      { silent: true },
    );
    if (probe.code === 0) return;
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error(`${row}: inner dockerd never accepted commands within 60s`);
}

async function stopAndRemove(runtime: string, container: string): Promise<void> {
  await run([runtime, "rm", "-f", container], { silent: true });
}

// ── Suite execution ─────────────────────────────────────────────────────────

type SuiteOutcome = {
  suite: string;
  status: "pass" | "fail" | "killed" | "skipped";
  exitCode: number | null;
  wallSeconds: number;
  logPath: string;
};

type RowOutcome = {
  row: string;
  status: "pass" | "fail" | "killed" | "build-failed";
  reason: string | null;
  wallSeconds: number;
  suites: SuiteOutcome[];
};

// Stage a per-row writable harbor home at /opt/harbor-test/work via an
// overlayfs mount. lowerdir is the bind-mounted host repo (read-only
// from the overlay's perspective); upperdir is in-container scratch
// where writes land. Without this, every `harbor config set/unset/
// update` call inside a row writes through the bind mount onto the
// host repo — clobbering ownership (root inside container vs. the host
// user) and racing with other rows.
//
// Overlayfs (vs. a directory of symlinks) gives nested containers a
// proper view: `harbor dev <script>` runs `docker run -v
// $harbor_home:$harbor_home denoland/deno:distroless …`. A symlink-tree
// dangles inside that nested container because the symlink targets
// (/opt/harbor-test/repo) are not mounted there. An overlay merge
// presents real directory entries that the inner bind-mount carries
// through.
async function stageHarborWork(
  runtime: string,
  container: string,
  row: string,
): Promise<void> {
  log(row, "staging /opt/harbor-test/work (selective copy of bind-mounted repo)...");
  // Real (non-hardlink, non-symlink) copy of the parts of the repo harbor
  // needs at runtime, into per-row writable scratch. Skips vendored trees
  // and host-only data:
  //   - services/webui (~900 MB): vendored Open WebUI source; harbor never
  //     reads it, only its compose.*.yml at services/ root.
  //   - app/: Tauri GUI sources, irrelevant to CLI tests.
  //   - docs/: markdown only.
  //   - tests/artifacts/: prior-run logs (huge, never read).
  //   - .env: stale state from the host; harbor.sh will recreate from
  //     profiles/default.env on first invocation.
  //   - node_modules/: vendored bytecode; nested deno fetches its own deps.
  //
  // `tar | tar` is the cheapest portable selective-copy: a single pass,
  // honours --exclude, preserves perms/ownership, and crosses the
  // device boundary (bind-mount → container layer) that defeated `cp -al`.
  //
  // Tear down any leftover from a `--keep` re-run before re-cloning.
  const excludes = [
    "./.env",
    "./.git",
    "./.history",
    "./app",
    "./docs",
    "./node_modules",
    "./services/webui",
    "./tests/artifacts",
  ].map((p) => `--exclude='${p}'`).join(" ");
  const setup = [
    "set -e",
    "rm -rf /opt/harbor-test/work",
    "mkdir -p /opt/harbor-test/work",
    `tar -C /opt/harbor-test/repo -cf - ${excludes} . | tar -C /opt/harbor-test/work -xf -`,
  ].join(" && ");
  const r = await run(
    [runtime, "exec", container, "bash", "-c", setup],
    { silent: true },
  );
  if (r.code !== 0) {
    throw new Error(
      `${row}: failed to stage harbor work overlay: ${r.stderr.trim() || r.stdout.trim()}`,
    );
  }
}

async function execSuite(
  probe: HostProbe,
  row: string,
  container: string,
  suite: Suite,
  logPath: string,
  installSource: "local" | "github",
): Promise<SuiteOutcome> {
  const t0 = performance.now();
  const cmd = [
    probe.runtime,
    "exec",
    "-e", `HARBOR_TEST_INSTALL_SOURCE=${installSource}`,
    "-e", "HARBOR_TEST_REPO=/opt/harbor-test/repo",
    // Per-row writable harbor home — see stageHarborWork above. harbor.sh
    // honours $HARBOR_HOME (line 5340-ish) and writes .env / compose cache
    // there instead of into the bind-mounted repo.
    "-e", "HARBOR_HOME=/opt/harbor-test/work",
    // harbor ln drops a symlink into ${HARBOR_CLI_PATH} (default ~/.local/bin).
    // docker exec is non-interactive and does not source profile/.bashrc, so we
    // inject that directory ourselves.
    "-e", "PATH=/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    container,
    "bash",
    `/opt/harbor-test/repo/tests/suites/${suite.file}`,
  ];
  const code = await runTeeToFile(cmd, logPath, `[${row}:${suite.short}] `);
  const wall = (performance.now() - t0) / 1000;
  return {
    suite: suite.short,
    status: code === 0 ? "pass" : "fail",
    exitCode: code,
    wallSeconds: wall,
    logPath,
  };
}

async function runRow(
  probe: HostProbe,
  row: string,
  suites: Suite[],
  runId: string,
  opts: {
    keep: boolean;
    rebuild: boolean;
    installSource: "local" | "github";
    // 0 disables the budget. Measured from the moment the row's image build
    // begins — covers the full end-to-end cost the orchestrator incurred.
    timeoutSeconds: number;
  },
): Promise<RowOutcome> {
  const hostArtifactsDir = `${ARTIFACTS_DIR}/${runId}/${row}`;
  await Deno.mkdir(hostArtifactsDir, { recursive: true });

  const outcome: RowOutcome = {
    row,
    status: "pass",
    reason: null,
    wallSeconds: 0,
    suites: [],
  };
  const rowStart = performance.now();

  // Build image
  try {
    await buildRowImage(probe.runtime, row, opts.rebuild);
  } catch (e) {
    outcome.status = "build-failed";
    outcome.reason = e instanceof Error ? e.message : String(e);
    outcome.wallSeconds = (performance.now() - rowStart) / 1000;
    return outcome;
  }

  const image = imageFor(row);
  const container = rowContainerName(runId, row);
  const isOpenRc = row.startsWith("alpine");

  // Clean up any stale container under the same name (previous --keep run).
  await run([probe.runtime, "rm", "-f", container], { silent: true });

  const runArgs = dockerRunArgs(probe, row, image, container, hostArtifactsDir);
  log(row, `starting container (${container})...`);
  const start = await run(runArgs, { silent: true });
  if (start.code !== 0) {
    outcome.status = "fail";
    outcome.reason = `container start failed: ${start.stderr.trim()}`;
    outcome.wallSeconds = (performance.now() - rowStart) / 1000;
    return outcome;
  }

  // Wall-time budget. When it fires we forcibly remove the container, which
  // causes any in-flight `docker exec` to exit non-zero — execSuite returns
  // a "fail" we then upgrade to "killed" based on the `killed` flag. Using
  // `rm -f` (vs `kill`) guarantees the container is gone regardless of
  // state, so the teardown in `finally` becomes a no-op.
  let killed = false;
  let timeoutHandle: number | null = null;
  if (opts.timeoutSeconds > 0) {
    timeoutHandle = setTimeout(() => {
      killed = true;
      log(row, `wall-time budget of ${opts.timeoutSeconds}s exceeded — killing container`);
      // Fire-and-forget: we don't need to await this, the in-flight exec
      // will return non-zero as soon as the container dies.
      run([probe.runtime, "rm", "-f", container], { silent: true }).catch(() => {});
    }, opts.timeoutSeconds * 1000);
  }

  try {
    await waitForSystemReady(probe.runtime, container, row, isOpenRc);
    await waitForInnerDocker(probe.runtime, container, row, isOpenRc);
    await stageHarborWork(probe.runtime, container, row);

    for (const suite of suites) {
      const logPath = `${hostArtifactsDir}/${suite.short}.log`;
      if (killed) {
        // Row was killed mid-run: record remaining suites as "killed" so the
        // matrix distinguishes timeout from real failure.
        outcome.suites.push({
          suite: suite.short,
          status: "killed",
          exitCode: null,
          wallSeconds: 0,
          logPath,
        });
        continue;
      }
      log(row, `suite '${suite.short}' starting → ${logPath}`);
      const result = await execSuite(
        probe,
        row,
        container,
        suite,
        logPath,
        opts.installSource,
      );
      // If the budget fired during this suite, the exec bailed because the
      // container was rm'd underneath it — relabel as killed, not fail.
      if (killed && result.status !== "pass") {
        result.status = "killed";
      }
      outcome.suites.push(result);
      if (result.status === "fail") {
        outcome.status = "fail";
        outcome.reason = outcome.reason ?? `${suite.short} failed (exit ${result.exitCode})`;
        // Continue running remaining suites — we want the full picture per row,
        // not early-exit on first failure.
      }
    }
  } catch (e) {
    // Timer-initiated rm_f makes in-flight exec/wait calls throw or fail;
    // classify those as "killed" rather than "fail".
    if (killed) {
      outcome.status = "killed";
      outcome.reason = `wall-time budget ${opts.timeoutSeconds}s exceeded`;
    } else {
      outcome.status = "fail";
      outcome.reason = e instanceof Error ? e.message : String(e);
    }
  } finally {
    if (timeoutHandle !== null) clearTimeout(timeoutHandle);
    if (killed) {
      outcome.status = "killed";
      outcome.reason = outcome.reason ?? `wall-time budget ${opts.timeoutSeconds}s exceeded`;
      // Container is already gone (the timer did `rm -f`); skip teardown.
    } else if (!opts.keep) {
      log(row, "tearing down container...");
      await stopAndRemove(probe.runtime, container);
    } else {
      log(row, `--keep: leaving ${container} running`);
    }
  }

  outcome.wallSeconds = (performance.now() - rowStart) / 1000;
  return outcome;
}

// ── Parallel scheduling ─────────────────────────────────────────────────────

async function runInPool<T, R>(
  items: T[],
  limit: number,
  fn: (item: T) => Promise<R>,
): Promise<R[]> {
  const results = new Array<R>(items.length);
  let next = 0;
  const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
    for (;;) {
      const i = next++;
      if (i >= items.length) return;
      results[i] = await fn(items[i]);
    }
  });
  await Promise.all(workers);
  return results;
}

// ── Reporting ────────────────────────────────────────────────────────────────

function formatSeconds(s: number): string {
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  const rem = Math.round(s - m * 60);
  return `${m}m${rem}s`;
}

function padRight(s: string, w: number): string {
  return s.length >= w ? s : s + " ".repeat(w - s.length);
}

function printTable(suites: Suite[], outcomes: RowOutcome[]) {
  const rowColW = Math.max(
    ...outcomes.map((o) => o.row.length),
    "row".length,
  );
  const cellW = Math.max(12, ...suites.map((s) => s.short.length + 2));

  const header =
    `| ${padRight("row", rowColW)} | ` +
    suites.map((s) => padRight(s.short, cellW)).join(" | ") +
    " |";
  const sep =
    "+-" + "-".repeat(rowColW) + "-+-" +
    suites.map(() => "-".repeat(cellW)).join("-+-") +
    "-+";

  console.log("");
  console.log(sep);
  console.log(header);
  console.log(sep);

  for (const o of outcomes) {
    const cells = suites.map((s) => {
      const r = o.suites.find((x) => x.suite === s.short);
      if (!r) {
        if (o.status === "build-failed") return padRight("BUILD", cellW);
        return padRight("-", cellW);
      }
      const sym = r.status === "pass" ? "PASS" : r.status.toUpperCase();
      return padRight(`${sym} ${formatSeconds(r.wallSeconds)}`, cellW);
    });
    console.log(`| ${padRight(o.row, rowColW)} | ${cells.join(" | ")} |`);
  }
  console.log(sep);
  console.log("");
}

function printErrors(outcomes: RowOutcome[]) {
  const bad = outcomes.filter((o) => o.status !== "pass");
  if (bad.length === 0) return;
  console.log("Failures:");
  for (const o of bad) {
    if (o.reason) {
      console.log(`  [${o.row}] ${o.reason}`);
    }
    for (const s of o.suites) {
      if (s.status !== "pass") {
        console.log(`  [${o.row}:${s.suite}] exit=${s.exitCode} log=${s.logPath}`);
      }
    }
  }
  console.log("");
}

function emitJson(runId: string, outcomes: RowOutcome[], suites: Suite[]) {
  const payload = {
    runId,
    suites: suites.map((s) => s.short),
    rows: outcomes.map((o) => ({
      row: o.row,
      status: o.status,
      reason: o.reason,
      wallSeconds: Number(o.wallSeconds.toFixed(2)),
      suites: o.suites.map((s) => ({
        suite: s.suite,
        status: s.status,
        exitCode: s.exitCode,
        wallSeconds: Number(s.wallSeconds.toFixed(2)),
        logPath: s.logPath,
      })),
    })),
  };
  console.log(JSON.stringify(payload, null, 2));
}

// ── Entry ───────────────────────────────────────────────────────────────────

async function main() {
  let args: Args;
  try {
    args = parseArgs(Deno.args);
  } catch (e) {
    console.error(`[test] ${e instanceof Error ? e.message : e}`);
    printHelp();
    Deno.exit(2);
  }
  if (args.help) {
    printHelp();
    Deno.exit(0);
  }

  log("test", "probing host environment...");
  let probe: HostProbe;
  try {
    probe = await probeHost(args.runtime);
  } catch (e) {
    console.error(`[test] ${e instanceof Error ? e.message : e}`);
    Deno.exit(1);
  }
  log(
    "test",
    `runtime=${probe.runtime} os=${probe.os} selinux=${
      probe.selinuxEnforcing ? "enforcing" : "permissive/off"
    } mountFlag='${probe.mountFlag}' labelDisable=${probe.securityLabelDisable}`,
  );

  let rows: string[];
  let suites: Suite[];
  try {
    rows = await discoverRows(args.distros);
    suites = await discoverSuites(args.suites);
  } catch (e) {
    console.error(`[test] ${e instanceof Error ? e.message : e}`);
    Deno.exit(2);
  }
  if (rows.length === 0) {
    console.error("[test] No rows selected.");
    Deno.exit(2);
  }
  if (suites.length === 0) {
    console.error("[test] No suites selected.");
    Deno.exit(2);
  }

  const runId = generateRunId();
  log("test", `run-id=${runId}`);
  log("test", `rows: ${rows.join(", ")}`);
  log("test", `suites: ${suites.map((s) => s.short).join(", ")}`);
  log("test", `jobs=${args.jobs} install-source=${args.installSource}`);

  // Build the shared base image once, up front. Rows reference it via
  // `FROM harbor-test/base AS harbor-base`, so it must exist before any
  // row build is launched in parallel.
  try {
    await buildBaseImage(probe.runtime, args.rebuild);
  } catch (e) {
    console.error(`[test] ${e instanceof Error ? e.message : e}`);
    Deno.exit(1);
  }

  const outcomes = await runInPool(rows, args.jobs, (row) =>
    runRow(probe, row, suites, runId, {
      keep: args.keep,
      rebuild: args.rebuild,
      installSource: args.installSource,
      timeoutSeconds: args.timeoutSeconds,
    }),
  );

  if (args.json) {
    emitJson(runId, outcomes, suites);
  } else {
    printTable(suites, outcomes);
    printErrors(outcomes);
  }

  const anyFail = outcomes.some(
    (o) => o.status !== "pass" || o.suites.some((s) => s.status !== "pass"),
  );
  Deno.exit(anyFail ? 1 : 0);
}

await main();
