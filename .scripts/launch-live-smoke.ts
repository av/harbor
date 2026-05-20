/// <reference lib="deno.ns" />

// Live end-user smoke for `harbor launch` host-tool adapters.
//
// This intentionally lives outside the containerized test suite: it is for a
// developer machine that already has Harbor, a compatible backend, and one or
// more host coding CLIs installed.

type Tool = "codex" | "claude" | "mi" | "opencode";

type Args = {
  backend: string | null;
  model: string | null;
  tools: Tool[];
  prompt: string;
  timeoutSeconds: number;
  configOnly: boolean;
  requireAll: boolean;
  harborBin: string;
  help: boolean;
};

const DEFAULT_TOOLS: Tool[] = ["codex", "claude", "mi", "opencode"];
const EXPECTED_RESPONSE = "HARBOR_LAUNCH_SMOKE_OK";
const DEFAULT_PROMPT =
  `Reply with exactly ${EXPECTED_RESPONSE} and no other text.`;

function usage(): string {
  return `Usage: harbor dev launch-live-smoke [options]

Runs installed host coding tools through harbor launch against a Harbor
backend. By default it checks codex,claude,mi,opencode and skips
tools that are not installed.

Options:
  --backend <service>      Harbor backend to use, such as ollama or llamacpp.
                           Default: let harbor launch auto-detect a running backend.
  --model <model>          Model to pass to harbor launch. Default: discover from /v1/models.
  --tools <list>           Comma-separated tools: codex,claude,mi,opencode.
  --tool <tool>            Select one tool. Can be repeated.
  --prompt <text>          Prompt used for live non-interactive smoke runs.
  --timeout <seconds>      Per-tool timeout. Default: 120.
  --config-only            Print each computed launch config instead of starting tools.
  --require-all            Fail if any selected tool is not installed.
  --harbor-bin <path>      Harbor executable. Default: ./harbor.sh.
  --help                   Show this help.

Examples:
  harbor up ollama
  harbor dev launch-live-smoke --backend ollama --model qwen3.5:4b
  harbor dev launch-live-smoke --tools codex,opencode --backend llamacpp --config-only
`;
}

function parseTool(raw: string): Tool {
  if (raw === "codex" || raw === "claude" || raw === "mi" || raw === "opencode") {
    return raw;
  }
  throw new Error(
    `Unknown tool '${raw}'. Expected one of: ${DEFAULT_TOOLS.join(",")}`,
  );
}

function parseArgs(raw: string[]): Args {
  const args: Args = {
    backend: null,
    model: null,
    tools: [],
    prompt: DEFAULT_PROMPT,
    timeoutSeconds: 120,
    configOnly: false,
    requireAll: false,
    harborBin: "./harbor.sh",
    help: false,
  };

  const takeValue = (
    i: number,
    inline: string | undefined,
    key: string,
  ): [string, number] => {
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
    const [key, inline] = arg.slice(2).split("=", 2) as [
      string,
      string | undefined,
    ];
    switch (key) {
      case "help":
      case "h":
        args.help = true;
        break;
      case "backend": {
        const [value, nextIndex] = takeValue(i, inline, key);
        args.backend = value;
        i = nextIndex;
        break;
      }
      case "model": {
        const [value, nextIndex] = takeValue(i, inline, key);
        args.model = value;
        i = nextIndex;
        break;
      }
      case "tools": {
        const [value, nextIndex] = takeValue(i, inline, key);
        args.tools = value.split(",").map((tool) => parseTool(tool.trim()))
          .filter(Boolean);
        i = nextIndex;
        break;
      }
      case "tool": {
        const [value, nextIndex] = takeValue(i, inline, key);
        args.tools.push(parseTool(value));
        i = nextIndex;
        break;
      }
      case "prompt": {
        const [value, nextIndex] = takeValue(i, inline, key);
        args.prompt = value;
        i = nextIndex;
        break;
      }
      case "timeout": {
        const [value, nextIndex] = takeValue(i, inline, key);
        const parsed = Number.parseInt(value, 10);
        if (!Number.isFinite(parsed) || parsed < 1) {
          throw new Error(
            `--timeout must be a positive integer, got '${value}'`,
          );
        }
        args.timeoutSeconds = parsed;
        i = nextIndex;
        break;
      }
      case "config-only":
        args.configOnly = true;
        break;
      case "require-all":
        args.requireAll = true;
        break;
      case "harbor-bin": {
        const [value, nextIndex] = takeValue(i, inline, key);
        args.harborBin = value;
        i = nextIndex;
        break;
      }
      default:
        throw new Error(`Unknown argument: --${key}`);
    }
  }

  if (args.tools.length === 0) args.tools = DEFAULT_TOOLS;
  args.tools = Array.from(new Set(args.tools));
  return args;
}

async function commandExists(cmd: string): Promise<boolean> {
  const probe = new Deno.Command("bash", {
    args: ["-lc", `command -v "${cmd}" >/dev/null 2>&1`],
    stdout: "null",
    stderr: "null",
  });
  const { code } = await probe.output();
  return code === 0;
}

function launchArgs(args: Args, tool: Tool): string[] {
  const cmd = [args.harborBin, "launch"];
  if (args.backend) cmd.push("--backend", args.backend);
  if (args.model) cmd.push("--model", args.model);

  if (args.configOnly) {
    cmd.push("--config");
    cmd.push(tool);
    return cmd;
  }

  cmd.push(tool);
  switch (tool) {
    case "codex":
      cmd.push(
        "exec",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--color",
        "never",
        args.prompt,
      );
      break;
    case "claude":
      cmd.push("-p", "--output-format", "text", args.prompt);
      break;
    case "mi":
      cmd.push("-p", args.prompt);
      break;
    case "opencode":
      cmd.push("run", "--pure", "--agent", "harbor-smoke", args.prompt);
      break;
  }
  return cmd;
}

type RunResult = {
  code: number;
  stdout: string;
  stderr: string;
};

function stripAnsi(value: string): string {
  return value.replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, "");
}

function includesExpectedSmokeResponse(value: string): boolean {
  return stripAnsi(value).split(/\r?\n/).some((line) =>
    line.trim() === EXPECTED_RESPONSE
  );
}

async function runWithTimeout(
  cmd: string[],
  timeoutSeconds: number,
): Promise<RunResult> {
  const child = new Deno.Command(cmd[0], {
    args: cmd.slice(1),
    stdin: "null",
    stdout: "piped",
    stderr: "piped",
  }).spawn();

  let timedOut = false;
  let forceTimeout: number | null = null;
  const status = child.status;
  const stdout = new Response(child.stdout).text();
  const stderr = new Response(child.stderr).text();
  const timeout = setTimeout(() => {
    timedOut = true;
    try {
      child.kill("SIGTERM");
    } catch {
      // Process may have exited between timeout firing and signal delivery.
    }
    forceTimeout = setTimeout(() => {
      try {
        child.kill("SIGKILL");
      } catch {
        // Process may have exited during the grace period.
      }
    }, 5000);
  }, timeoutSeconds * 1000);

  try {
    const { code } = await status;
    return {
      code: timedOut && code === 0 ? 124 : code,
      stdout: await stdout,
      stderr: await stderr,
    };
  } finally {
    clearTimeout(timeout);
    if (forceTimeout !== null) clearTimeout(forceTimeout);
  }
}

async function main() {
  const args = parseArgs(Deno.args);
  if (args.help) {
    console.log(usage());
    return;
  }

  let ran = 0;
  let failed = 0;
  const missing: Tool[] = [];

  for (const tool of args.tools) {
    if (!args.configOnly && !(await commandExists(tool))) {
      missing.push(tool);
      console.error(`[launch-live-smoke] skip ${tool}: not installed`);
      continue;
    }

    const cmd = launchArgs(args, tool);
    console.error(
      `[launch-live-smoke] ${tool}: ${
        cmd.map((part) => JSON.stringify(part)).join(" ")
      }`,
    );
    const result = await runWithTimeout(cmd, args.timeoutSeconds);
    if (result.stdout.length > 0) {
      await Deno.stdout.write(new TextEncoder().encode(result.stdout));
    }
    if (result.stderr.length > 0) {
      await Deno.stderr.write(new TextEncoder().encode(result.stderr));
    }
    ran++;
    if (result.code !== 0) {
      failed++;
      console.error(
        `[launch-live-smoke] ${tool}: failed with exit ${result.code}`,
      );
      continue;
    }

    if (
      !args.configOnly &&
      !includesExpectedSmokeResponse(`${result.stdout}\n${result.stderr}`)
    ) {
      failed++;
      console.error(
        `[launch-live-smoke] ${tool}: failed: expected smoke response '${EXPECTED_RESPONSE}' was not found as an exact output line`,
      );
    }
  }

  if (args.requireAll && missing.length > 0) {
    console.error(
      `[launch-live-smoke] missing required tool(s): ${missing.join(", ")}`,
    );
    Deno.exit(1);
  }

  if (ran === 0) {
    console.error("[launch-live-smoke] no selected tools were run");
    Deno.exit(1);
  }

  if (failed > 0) {
    Deno.exit(1);
  }

  console.error(
    `[launch-live-smoke] OK (${ran} run, ${missing.length} skipped)`,
  );
}

if (import.meta.main) {
  main().catch((error) => {
    console.error(
      `[launch-live-smoke] ERROR: ${
        error instanceof Error ? error.message : String(error)
      }`,
    );
    Deno.exit(1);
  });
}
