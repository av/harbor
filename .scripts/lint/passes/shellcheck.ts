/// <reference lib="deno.ns" />
/// <reference lib="dom" />

// Shellcheck pass. Invokes the external `shellcheck` binary with JSON output
// and translates its findings into the shared Finding type.
//
// If shellcheck is not on PATH:
//   - Linux: emit the single apt/dnf command the user must run. No silent
//     install — we do not want to touch the user's system from a linter.
//   - macOS: emit the brew command.
// In either case we return an error-severity "pass-unavailable" finding so
// the run exits non-zero, rather than silently skipping the pass.

import type { Finding } from "../types.ts";
import { collectFiles, relative } from "../util.ts";

export interface ShellcheckOptions {
  root: string;
  globs: string[];
  exclude?: string[];
  severity?: "error" | "warning" | "info" | "style";
  fileFilter?: string[] | null;
}

interface ShellcheckJson {
  comments: Array<{
    file: string;
    line: number;
    column: number;
    level: "error" | "warning" | "info" | "style";
    code: number;
    message: string;
  }>;
}

async function shellcheckVersion(): Promise<string | null> {
  try {
    const p = new Deno.Command("shellcheck", {
      args: ["--version"],
      stdout: "piped",
      stderr: "null",
    });
    const { code, stdout } = await p.output();
    if (code !== 0) return null;
    const text = new TextDecoder().decode(stdout);
    const m = text.match(/version:\s*(\S+)/);
    return m ? m[1] : text.trim();
  } catch {
    return null;
  }
}

function installHint(): string {
  const plat = Deno.build.os;
  if (plat === "darwin") return "brew install shellcheck";
  // On Linux the apt/dnf name differs; give both so users pick the one their
  // package manager knows about.
  return "sudo apt-get install -y shellcheck   # Debian/Ubuntu\n" +
    "sudo dnf install -y ShellCheck        # Fedora/RHEL";
}

export async function runShellcheck(opts: ShellcheckOptions): Promise<Finding[]> {
  const have = await shellcheckVersion();
  if (!have) {
    return [{
      file: "(host)",
      pass: "shellcheck",
      rule: "pass-unavailable",
      severity: "error",
      message:
        "shellcheck is not installed. Install it and retry:\n" + installHint(),
    }];
  }

  const severity = opts.severity ?? "warning";
  const files = await collectFiles(opts.root, opts.globs, opts.exclude ?? []);
  const filtered = opts.fileFilter
    ? files.filter((f) => opts.fileFilter!.includes(relative(opts.root, f)))
    : files;
  if (filtered.length === 0) return [];

  const proc = new Deno.Command("shellcheck", {
    args: [
      "--severity", severity,
      "--format", "json1",
      "--external-sources",
      ...filtered,
    ],
    stdout: "piped",
    stderr: "piped",
  });
  const { code, stdout, stderr } = await proc.output();
  const out = new TextDecoder().decode(stdout);

  if (code !== 0 && out.trim() === "") {
    const err = new TextDecoder().decode(stderr).trim();
    return [{
      file: "(shellcheck)",
      pass: "shellcheck",
      rule: "exec-error",
      severity: "error",
      message: `shellcheck invocation failed: ${err || `exit ${code}`}`,
    }];
  }

  let parsed: ShellcheckJson;
  try {
    parsed = JSON.parse(out);
  } catch (e) {
    return [{
      file: "(shellcheck)",
      pass: "shellcheck",
      rule: "parse-error",
      severity: "error",
      message: `Unable to parse shellcheck JSON: ${e instanceof Error ? e.message : e}`,
    }];
  }

  return parsed.comments.map((c) => ({
    file: relative(opts.root, c.file),
    line: c.line,
    column: c.column,
    pass: "shellcheck" as const,
    rule: `SC${c.code}`,
    severity: (c.level === "error" ? "error" : "warning") as "error" | "warning",
    message: c.message,
  }));
}
