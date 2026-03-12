/// <reference lib="deno.ns" />
/// <reference lib="dom" />

// Run via: harbor dev integration

type CliArgs = {
  "keep-vm": boolean;
  verbose: boolean;
  "inside-vm": boolean;
  "no-provision": boolean;
  "reuse-vm": boolean;
  "artifacts-dir"?: string;
  provider: string;
  "vm-name"?: string;
};

function parseArgs(rawArgs: string[]): CliArgs {
  const parsed: CliArgs = {
    provider: "multipass",
    "keep-vm": false,
    verbose: false,
    "inside-vm": false,
    "no-provision": false,
    "reuse-vm": false,
  };

  for (let index = 0; index < rawArgs.length; index += 1) {
    const arg = rawArgs[index];

    if (!arg.startsWith("--")) {
      continue;
    }

    const [rawKey, inlineValue] = arg.slice(2).split("=", 2);

    switch (rawKey) {
      case "keep-vm":
      case "verbose":
      case "inside-vm":
      case "no-provision":
      case "reuse-vm":
        parsed[rawKey] = inlineValue === undefined ? true : inlineValue !== "false";
        break;
      case "artifacts-dir":
      case "provider":
      case "vm-name": {
        const nextValue = inlineValue ?? rawArgs[index + 1];
        if (nextValue === undefined || nextValue.startsWith("--")) {
          throw new Error(`Missing value for --${rawKey}`);
        }
        parsed[rawKey] = nextValue;
        if (inlineValue === undefined) {
          index += 1;
        }
        break;
      }
      default:
        throw new Error(`Unknown argument: --${rawKey}`);
    }
  }

  return parsed;
}

const args = parseArgs(Deno.args);

const isGuestMode = args["inside-vm"] || args["no-provision"];
const keepVm = args["keep-vm"];
const reuseVm = args["reuse-vm"];
const verbose = args.verbose;
const artifactsDir = args["artifacts-dir"];
const provider = args.provider;
const requestedVmName = args["vm-name"];

const MOUNT_TARGET = "/workspace/harbor";
const MOUNT_READY_FILE = `${MOUNT_TARGET}/integration/guest/run.sh`;
const REUSABLE_VM_NAME = "harbor-int";

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms.toFixed(0)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function logTiming(phase: string, startMs: number) {
  log("host", `${phase} completed in ${formatDuration(performance.now() - startMs)}.`);
}

async function withTiming<T>(phase: string, fn: () => Promise<T>): Promise<T> {
  const startMs = performance.now();
  try {
    return await fn();
  } finally {
    logTiming(phase, startMs);
  }
}

type MultipassInfoResponse = {
  errors?: Array<{ message?: string }>;
  info?: Record<string, { state?: string }>;
};

async function getVmState(vmName: string): Promise<string | null> {
  const result = await runCommand(["multipass", "info", vmName, "--format", "json"], {
    silent: true,
  });
  if (result.exitCode !== 0) {
    return null;
  }

  try {
    const parsed = JSON.parse(result.stdout) as MultipassInfoResponse;
    return parsed.info?.[vmName]?.state ?? null;
  } catch {
    return null;
  }
}

function isAlreadyMountedError(output: string): boolean {
  return /already mounted|mount already exists|is already mounted|already exists/i.test(output);
}

async function waitForMountReady(vmName: string): Promise<boolean> {
  const timeoutMs = 15_000;
  const intervalMs = 500;
  const deadline = Date.now() + timeoutMs;
  let attempt = 0;

  while (Date.now() < deadline) {
    attempt += 1;
    const check = await runCommand(
      ["multipass", "exec", vmName, "--", "test", "-f", MOUNT_READY_FILE],
      { silent: true }
    );
    if (check.exitCode === 0) {
      return true;
    }

    if (verbose) log("host", `Mount check attempt ${attempt} failed, retrying...`);
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }

  return false;
}

function log(prefix: string, msg: string) {
  console.log(`[${prefix}] ${msg}`);
}

async function runCommand(
  cmd: string[],
  opts: { silent?: boolean } = {}
): Promise<{ exitCode: number; stdout: string; stderr: string }> {
  const proc = new Deno.Command(cmd[0], {
    args: cmd.slice(1),
    stdout: "piped",
    stderr: "piped",
  });
  const { code, stdout, stderr } = await proc.output();
  const outStr = new TextDecoder().decode(stdout);
  const errStr = new TextDecoder().decode(stderr);
  if (!opts.silent) {
    if (outStr) Deno.stdout.writeSync(new TextEncoder().encode(outStr));
    if (errStr) Deno.stderr.writeSync(new TextEncoder().encode(errStr));
  }
  return { exitCode: code, stdout: outStr, stderr: errStr };
}

async function runLive(cmd: string[]): Promise<number> {
  const proc = new Deno.Command(cmd[0], {
    args: cmd.slice(1),
    stdin: "inherit",
    stdout: "inherit",
    stderr: "inherit",
  });
  const { code } = await proc.output();
  return code;
}

// ── GUEST MODE ────────────────────────────────────────────────────────────────

if (isGuestMode) {
  log("integration", "Running guest-side flow");

  const guestArgs = ["bash", "./integration/guest/run.sh", "--inside-vm"];
  if (verbose) guestArgs.push("--verbose");
  if (artifactsDir) guestArgs.push("--artifacts-dir", artifactsDir);

  const exitCode = await runLive(guestArgs);
  Deno.exit(exitCode);
}

// ── HOST MODE ─────────────────────────────────────────────────────────────────

if (provider !== "multipass") {
  log("host", `Unsupported provider: ${provider}. Only "multipass" is supported.`);
  Deno.exit(1);
}

// 1. Verify multipass is installed
log("host", "Checking for multipass...");
const totalStartMs = performance.now();
const versionCheck = await withTiming("Multipass verification", async () => {
  return await runCommand(["multipass", "version"], { silent: true });
});
if (versionCheck.exitCode !== 0) {
  log("host", "ERROR: multipass is not installed or not on PATH.");
  log("host", "Install it from https://multipass.run and try again.");
  Deno.exit(1);
}
if (verbose) log("host", `multipass: ${versionCheck.stdout.trim()}`);

// 1a. Remove stale named pipes from services/ — they cause EIO inside 9P VM mounts
await runCommand(["bash", "-c", "find ./services -type p -delete 2>/dev/null || true"], { silent: true });

// 2. Choose VM mode and name
const vmName = requestedVmName ?? (reuseVm ? REUSABLE_VM_NAME : `harbor-int-${Date.now()}`);
const shouldPreserveVm = reuseVm || keepVm;
log("host", `VM name: ${vmName}`);

let suiteExitCode = 1;

try {
  // 3. Launch or start Ubuntu LTS guest
  await withTiming("VM launch/start", async () => {
    if (!reuseVm) {
      log("host", "Launching VM...");
      const launchCode = await runLive([
        "multipass", "launch",
        "--name", vmName,
        "--cpus", "2",
        "--memory", "4G",
        "--disk", "20G",
        "--cloud-init", "./integration/cloud-init/multipass.yaml",
      ]);
      if (launchCode !== 0) {
        log("host", "ERROR: Failed to launch VM. Aborting.");
        Deno.exit(1);
      }
      log("host", "VM launched successfully.");
      return;
    }

    const vmState = await getVmState(vmName);
    if (vmState === null) {
      log("host", "Launching reusable VM...");
      const launchCode = await runLive([
        "multipass", "launch",
        "--name", vmName,
        "--cpus", "2",
        "--memory", "4G",
        "--disk", "20G",
        "--cloud-init", "./integration/cloud-init/multipass.yaml",
      ]);
      if (launchCode !== 0) {
        log("host", "ERROR: Failed to launch VM. Aborting.");
        Deno.exit(1);
      }
      log("host", "Reusable VM launched successfully.");
      return;
    }

    if (vmState.toLowerCase() === "running") {
      log("host", `Reusing running VM "${vmName}".`);
      return;
    }

    log("host", `Starting existing VM "${vmName}"...`);
    const startCode = await runLive(["multipass", "start", vmName]);
    if (startCode !== 0) {
      log("host", "ERROR: Failed to start existing VM. Aborting.");
      Deno.exit(1);
    }
    log("host", `VM "${vmName}" is running.`);
  });

  // 4. Mount the repo into the guest
  await withTiming("Mount setup", async () => {
    log("host", "Mounting repo into VM...");
    const mountResult = await runCommand([
      "multipass", "mount", ".", `${vmName}:${MOUNT_TARGET}`,
    ]);
    if (mountResult.exitCode === 0) {
      return;
    }

    const mountOutput = `${mountResult.stdout}\n${mountResult.stderr}`;
    if (reuseVm && isAlreadyMountedError(mountOutput)) {
      log("host", "Repo mount already exists; continuing.");
      return;
    }

    log("host", "ERROR: Failed to mount repo into VM.");
    Deno.exit(1);
  });

  // 5. Wait for mount to be available
  log("host", `Waiting for mount to expose ${MOUNT_READY_FILE}...`);
  const mountReady = await withTiming("Mount readiness wait", async () => {
    return await waitForMountReady(vmName);
  });
  if (!mountReady) {
    log("host", "ERROR: Mount never became available inside VM.");
    Deno.exit(1);
  }
  log("host", "Mount is ready.");

  // 6. Run the guest-side integration runner
  const guestCmd = [
    "multipass", "exec", vmName, "--",
    "bash", "/workspace/harbor/integration/guest/run.sh", "--inside-vm",
  ];
  if (verbose) guestCmd.push("--verbose");
  if (artifactsDir) guestCmd.push("--artifacts-dir", artifactsDir);

  log("host", "Running integration suite inside VM...");
  suiteExitCode = await withTiming("Guest execution", async () => {
    return await runLive(guestCmd);
  });
  log("host", `Suite finished with exit code ${suiteExitCode}.`);

} finally {
  // 7. Collect artifacts from guest
  const hostArtifactsDir = artifactsDir ?? "./integration/artifacts";
  await withTiming("Artifact collection", async () => {
    log("host", `Collecting artifacts to ${hostArtifactsDir}...`);
    try {
      await Deno.mkdir(hostArtifactsDir, { recursive: true });
      await runLive([
        "multipass", "transfer", "--recursive",
        `${vmName}:/workspace/harbor/integration/artifacts/.`,
        hostArtifactsDir,
      ]);
    } catch (e) {
      log("host", `Warning: artifact collection failed: ${e instanceof Error ? e.message : e}`);
    }
  });

  // 8. Tear down VM unless --keep-vm
  await withTiming("Teardown", async () => {
    if (reuseVm) {
      log("host", `--reuse-vm set — VM "${vmName}" preserved.`);
      return;
    }

    if (keepVm) {
      log("host", `--keep-vm set — VM "${vmName}" preserved.`);
      return;
    }

    log("host", `Cleaning up VM "${vmName}"...`);
    await runLive(["multipass", "stop", vmName]);
    await runLive(["multipass", "delete", vmName]);
    await runLive(["multipass", "purge"]);
    log("host", "VM deleted and purged.");
  });

  if (shouldPreserveVm && reuseVm && keepVm) {
    log("host", `VM "${vmName}" preserved for reuse.`);
  }
}

logTiming("Total elapsed time", totalStartMs);

// 9. Exit with suite exit code
Deno.exit(suiteExitCode);
