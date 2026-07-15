/// <reference lib="deno.ns" />
/// <reference lib="dom" />

// Harbor lint orchestrator.
//
// Runs four independent passes and aggregates their findings:
//   - shellcheck: general bash hygiene (SC codes).
//   - bash:      Harbor-specific portability rules (HARBORxxx) loaded from
//                .scripts/lint/rules.yaml.
//   - compose:   Harbor compose-file conventions (container naming, env_file
//                layout, networks, volumes, build context, …).
//   - boost:     Boost module integrity (zero-byte `.py` files under load paths).
//
// By default every pass runs over every applicable file. Flags narrow the
// scope:
//   --shellcheck       only shellcheck
//   --rules            only bash rules
//   --compose          only compose rules
// Passing multiple of these combines them; passing none runs all three.

import { runShellcheck } from "./passes/shellcheck.ts";
import { runBashRules } from "./passes/bash.ts";
import { runCompose } from "./passes/compose.ts";
import { runBoost } from "./passes/boost.ts";
import type { Finding } from "./types.ts";

// ── Arg parsing ──────────────────────────────────────────────────────────────

type Args = {
  help: boolean;
  json: boolean;
  shellcheck: boolean | null; // null = "unspecified"
  rules: boolean | null;
  compose: boolean | null;
  boost: boolean | null;
  files: string[] | null;
  severity: Set<"error" | "warning">;
};

function parseArgs(raw: string[]): Args {
  const args: Args = {
    help: false,
    json: false,
    shellcheck: null,
    rules: null,
    compose: null,
    boost: null,
    files: null,
    severity: new Set(["error", "warning"]),
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
      case "json":
        args.json = true;
        break;
      case "shellcheck":
        args.shellcheck = true;
        break;
      case "rules":
        args.rules = true;
        break;
      case "compose":
        args.compose = true;
        break;
      case "boost":
        args.boost = true;
        break;
      case "files": {
        const [v, ni] = takeValue(i, inline, rawKey);
        args.files = v.split(",").map((s) => s.trim()).filter(Boolean);
        i = ni;
        break;
      }
      case "severity": {
        const [v, ni] = takeValue(i, inline, rawKey);
        const parts = v.split(",").map((s) => s.trim().toLowerCase());
        args.severity = new Set();
        for (const p of parts) {
          if (p === "error" || p === "warning") args.severity.add(p);
          else throw new Error(`--severity values must be error or warning (got "${p}")`);
        }
        if (args.severity.size === 0) {
          throw new Error("--severity requires at least one value");
        }
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
  console.log(`Usage: harbor dev lint [options]

Options:
  --shellcheck              Run only the shellcheck pass.
  --rules                   Run only the bash project rules pass.
  --compose                 Run only the compose-file conventions pass.
  --boost                   Run only the Boost module integrity pass.
                            (default: run all four)
  --files a.sh,b.sh,…       Limit all passes to the listed files
                            (repo-relative paths).
  --severity error[,warning]  Findings to report; default error+warning.
                            Exit non-zero iff any reported finding is an error.
  --json                    Machine-readable JSON output.
  --help                    Show this help.

Examples:
  harbor dev lint
  harbor dev lint --shellcheck
  harbor dev lint --rules --files harbor.sh,install.sh
  harbor dev lint --compose --json
`);
}

// ── Paths ────────────────────────────────────────────────────────────────────

const REPO_ROOT = Deno.cwd();

const BASH_GLOBS = [
  "harbor.sh",
  "install.sh",
  "requirements.sh",
  "services/**/*.sh",
  "shared/**/*.sh",
  "tests/**/*.sh",
  ".scripts/**/*.sh",
];
const BASH_EXCLUDES = [
  // Rule fixtures are self-test fodder for the bash pass; shellcheck does not
  // help us there (fixtures intentionally break the rule).
  ".scripts/lint/fixtures/**/*.sh",
  // Vendored third-party caches are not Harbor code.
  "lemonade/cache/**/*.sh",
  "node_modules/**/*.sh",
  ".deno-cache/**/*.sh",
  "services/**/.venv/**/*.sh",
  ".claude/worktrees/**/*.sh",
  // Test artifacts contain staged copies of the repo; linting them double-counts
  // findings and flags intentional-failure fixtures.
  "tests/artifacts/**/*.sh",
];

const RULES_PATH = `${REPO_ROOT}/.scripts/lint/rules.yaml`;

// ── Reporting ────────────────────────────────────────────────────────────────

function passesSelected(args: Args): {
  shellcheck: boolean;
  rules: boolean;
  compose: boolean;
  boost: boolean;
} {
  const anySelected = args.shellcheck === true || args.rules === true ||
    args.compose === true || args.boost === true;
  if (anySelected) {
    return {
      shellcheck: args.shellcheck === true,
      rules: args.rules === true,
      compose: args.compose === true,
      boost: args.boost === true,
    };
  }
  return { shellcheck: true, rules: true, compose: true, boost: true };
}

function printHuman(findings: Finding[], severity: Set<"error" | "warning">) {
  const keep = findings.filter((f) => severity.has(f.severity));
  if (keep.length === 0) {
    console.log("clean.");
    return;
  }
  const byFile = new Map<string, Finding[]>();
  for (const f of keep) {
    const list = byFile.get(f.file) ?? [];
    list.push(f);
    byFile.set(f.file, list);
  }
  const files = [...byFile.keys()].sort();
  let errors = 0;
  let warnings = 0;
  for (const file of files) {
    console.log(file);
    const list = byFile.get(file)!;
    list.sort((a, b) => (a.line ?? 0) - (b.line ?? 0) || a.rule.localeCompare(b.rule));
    for (const f of list) {
      const sev = f.severity === "error" ? "E" : "W";
      if (f.severity === "error") errors++;
      else warnings++;
      const pos = f.line !== undefined
        ? `:${f.line}${f.column !== undefined ? `:${f.column}` : ""}`
        : "";
      console.log(`  ${pos.padEnd(8)} ${sev} ${f.pass}/${f.rule}`);
      for (const line of f.message.split("\n")) {
        if (line.trim()) console.log(`           ${line}`);
      }
      if (f.fix) {
        for (const line of f.fix.split("\n")) {
          if (line.trim()) console.log(`           fix: ${line}`);
        }
      }
    }
    console.log();
  }
  console.log(`${errors} error(s), ${warnings} warning(s) across ${files.length} file(s).`);
}

// ── Entry ────────────────────────────────────────────────────────────────────

async function main() {
  let args: Args;
  try {
    args = parseArgs(Deno.args);
  } catch (e) {
    console.error(`[lint] ${e instanceof Error ? e.message : e}`);
    printHelp();
    Deno.exit(2);
  }
  if (args.help) {
    printHelp();
    Deno.exit(0);
  }

  const sel = passesSelected(args);
  const findings: Finding[] = [];

  if (sel.shellcheck) {
    findings.push(
      ...(await runShellcheck({
        root: REPO_ROOT,
        globs: BASH_GLOBS,
        exclude: BASH_EXCLUDES,
        severity: "warning",
        fileFilter: args.files,
      })),
    );
  }

  if (sel.rules) {
    findings.push(
      ...(await runBashRules({
        root: REPO_ROOT,
        rulesPath: RULES_PATH,
        fileFilter: args.files,
        globalExclude: BASH_EXCLUDES,
      })),
    );
  }

  if (sel.compose) {
    findings.push(
      ...(await runCompose({
        root: REPO_ROOT,
        fileFilter: args.files,
      })),
    );
  }

  if (sel.boost) {
    findings.push(
      ...(await runBoost({
        root: REPO_ROOT,
        fileFilter: args.files,
      })),
    );
  }

  const reported = findings.filter((f) => args.severity.has(f.severity));
  if (args.json) {
    console.log(JSON.stringify({ findings: reported }, null, 2));
  } else {
    printHuman(findings, args.severity);
  }

  const anyError = reported.some((f) => f.severity === "error");
  Deno.exit(anyError ? 1 : 0);
}

await main();
