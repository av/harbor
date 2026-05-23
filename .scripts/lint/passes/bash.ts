/// <reference lib="deno.ns" />
/// <reference lib="dom" />

// Bash compatibility rules pass.
//
// Rules live as data in .scripts/lint/rules.yaml. Each rule pairs an ID, a
// regex, and a human-readable fix hint. We run each rule's regex over the
// lines of every matching file and emit findings. Inline escapes via
// `# harbor-lint disable=<RULE_ID>` on the offending line are honoured.
//
// Regex is deliberate: these rules match specific, shallow portability
// patterns where a parser would add weight without catching more. Upgrade
// to AST-based matching only if the FP rate becomes a real cost.

import { parse as parseYaml } from "https://deno.land/std/yaml/mod.ts";
import { expandGlob } from "https://deno.land/std/fs/mod.ts";

import type { Finding } from "../types.ts";
import { collectFiles, relative } from "../util.ts";

interface RawRule {
  id: string;
  name: string;
  severity: "error" | "warning";
  pattern: string;
  files: string[];
  exclude?: string[];
  message: string;
  fix?: string;
}

interface CompiledRule extends RawRule {
  regex: RegExp;
}

async function loadRules(rulesPath: string): Promise<CompiledRule[]> {
  const raw = await Deno.readTextFile(rulesPath);
  const doc = parseYaml(raw) as { rules?: RawRule[] } | null;
  if (!doc || !Array.isArray(doc.rules)) {
    throw new Error(`${rulesPath}: expected top-level \`rules:\` array`);
  }
  return doc.rules.map((r) => {
    if (!r.id || !r.name || !r.pattern) {
      throw new Error(`Rule missing id/name/pattern: ${JSON.stringify(r)}`);
    }
    return { ...r, regex: new RegExp(r.pattern) };
  });
}

// Check whether `# harbor-lint disable=RULEID[,RULEID,…]` is present on the
// line and covers the given rule. Silences only the exact IDs listed.
function isDisabled(line: string, ruleId: string): boolean {
  const m = line.match(/#\s*harbor-lint\s+disable\s*=\s*([A-Z0-9_,\s]+)/i);
  if (!m) return false;
  return m[1].split(",").map((s) => s.trim()).includes(ruleId);
}

// Drop the bash comment portion of a line so rule regexes do not fire on
// documentation that mentions the forbidden pattern (e.g. spec refs, rule
// fixtures). The stripper is quote-aware for ' and " and treats `#` as a
// comment only at start-of-line or preceded by whitespace — matching bash's
// own lexer behaviour closely enough for our rules.
function stripComment(line: string): string {
  let inSingle = false;
  let inDouble = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (inSingle) {
      if (c === "'") inSingle = false;
    } else if (inDouble) {
      if (c === "\\") i++;
      else if (c === '"') inDouble = false;
    } else {
      if (c === "'") inSingle = true;
      else if (c === '"') inDouble = true;
      else if (c === "#" && (i === 0 || /\s/.test(line[i - 1]))) {
        return line.slice(0, i);
      }
    }
  }
  return line;
}

export interface BashOptions {
  root: string;
  rulesPath: string;
  fileFilter?: string[] | null; // if set, only lint these paths (repo-relative)
  globalExclude?: string[]; // orchestrator-level excludes applied after rule globs
}

export async function runBashRules(opts: BashOptions): Promise<Finding[]> {
  const rules = await loadRules(opts.rulesPath);
  const globalDrop = new Set<string>();
  for (const g of opts.globalExclude ?? []) {
    for await (const entry of expandGlob(g, { root: opts.root, includeDirs: false, globstar: true })) {
      if (entry.isFile) globalDrop.add(entry.path);
    }
  }
  const findings: Finding[] = [];

  for (const rule of rules) {
    const files = await collectFiles(opts.root, rule.files, rule.exclude ?? []);
    for (const abs of files) {
      const rel = relative(opts.root, abs);
      if (opts.fileFilter) {
        // When the user explicitly names a file on the command line, honour
        // that even if the global-exclude set also covers it — this is how
        // rule fixtures are self-tested.
        if (!opts.fileFilter.includes(rel)) continue;
      } else if (globalDrop.has(abs)) {
        continue;
      }
      let raw: string;
      try {
        raw = await Deno.readTextFile(abs);
      } catch {
        continue;
      }
      const lines = raw.split(/\r?\n/);
      for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        const code = stripComment(line);
        if (!code.trim()) continue;
        // Fresh regex per line: global-flag state would leak otherwise.
        const re = new RegExp(rule.pattern, rule.regex.flags);
        const m = re.exec(code);
        if (!m) continue;
        if (isDisabled(line, rule.id)) continue;
        findings.push({
          file: rel,
          line: i + 1,
          column: (m.index ?? 0) + 1,
          pass: "bash",
          rule: rule.id,
          severity: rule.severity,
          message: `${rule.name}: ${rule.message.trim()}`,
          fix: rule.fix?.trim(),
        });
      }
    }
  }
  return findings;
}
