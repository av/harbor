/// <reference lib="deno.ns" />
/// <reference lib="dom" />

// Self-test harness for the Harbor lint passes.
//
// Sections:
//   1. Bash rules pass — for each rule ID that has a fixture directory, run
//      the bash-rules pass against fail.sh and pass.sh and assert hit counts.
//   2. Compose pass — per compose rule, lint a fail.yml fixture and assert
//      the rule fires `expect-hits` times; lint pass.yml and assert zero
//      findings on the targeted rule.
//   3. Shellcheck pass — single fixture pair. Skipped (with a clear note)
//      when the shellcheck binary is unavailable.
//   4. Orchestrator — help-text discoverability and exit-code contract.
//
// The harness exits non-zero on any mismatch in any section; SKIP rows are
// not failures. Tightening a regex, loosening it, or breaking a downstream
// pass without updating the corresponding fixture trips this test.
//
// Invoked via `harbor dev lint-self-test` (see .scripts/lint-self-test.ts)
// and from CI (see .github/workflows/lint.yml).

import { parse as parseYaml } from "https://deno.land/std/yaml/mod.ts";
import { runBashRules } from "./passes/bash.ts";
import { runCompose } from "./passes/compose.ts";
import { runShellcheck } from "./passes/shellcheck.ts";
import type { Finding } from "./types.ts";

interface RawRule {
  id: string;
  name: string;
}

const REPO_ROOT = Deno.cwd();
const RULES_PATH = `${REPO_ROOT}/.scripts/lint/rules.yaml`;
const FIXTURES_ROOT = `${REPO_ROOT}/.scripts/lint/fixtures`;
const COMPOSE_FIXTURES_ROOT = `${FIXTURES_ROOT}/compose`;
const SHELLCHECK_FIXTURES_ROOT = `${FIXTURES_ROOT}/shellcheck`;
const RUN_TS = `${REPO_ROOT}/.scripts/lint/run.ts`;

async function loadRuleIds(): Promise<Map<string, string>> {
  const raw = await Deno.readTextFile(RULES_PATH);
  const doc = parseYaml(raw) as { rules?: RawRule[] } | null;
  if (!doc || !Array.isArray(doc.rules)) {
    throw new Error(`${RULES_PATH}: expected top-level \`rules:\` array`);
  }
  const byId = new Map<string, string>();
  for (const r of doc.rules) byId.set(r.id, r.name);
  return byId;
}

async function listFixtureDirs(): Promise<string[]> {
  const ids: string[] = [];
  for await (const entry of Deno.readDir(FIXTURES_ROOT)) {
    if (entry.isDirectory && /^HARBOR\d+$/.test(entry.name)) {
      ids.push(entry.name);
    }
  }
  ids.sort();
  return ids;
}

// Parse `# expect-hits: N` from the top of a fixture.
async function expectedHits(path: string): Promise<number | null> {
  const text = await Deno.readTextFile(path);
  const m = text.match(/^#\s*expect-hits:\s*(\d+)\s*$/m);
  return m ? parseInt(m[1], 10) : null;
}

// Parse `# expect-rule: <name>` from the top of a fixture.
async function expectedRule(path: string): Promise<string | null> {
  const text = await Deno.readTextFile(path);
  const m = text.match(/^#\s*expect-rule:\s*([\w-]+)\s*$/m);
  return m ? m[1] : null;
}

// Run the bash-rules pass once across the union of fixtures and return a
// nested counter: findings[file][ruleId] = count. The bash pass does
// per-rule globbing over the full repo, so invoking it per fixture turns
// into O(N × fullRepoGlob) wall-clock. Batching keeps the harness fast.
async function collectBashHits(files: string[]): Promise<Map<string, Map<string, number>>> {
  const findings = await runBashRules({
    root: REPO_ROOT,
    rulesPath: RULES_PATH,
    fileFilter: files,
    globalExclude: [],
  });
  const out = new Map<string, Map<string, number>>();
  for (const f of files) out.set(f, new Map());
  for (const f of findings) {
    const bucket = out.get(f.file);
    if (!bucket) continue;
    bucket.set(f.rule, (bucket.get(f.rule) ?? 0) + 1);
  }
  return out;
}

// ── Bash section ─────────────────────────────────────────────────────────────

interface BashRow {
  ruleId: string;
  ruleName: string;
  failExpected: number | null;
  failActual: number;
  passActual: number;
  ok: boolean;
  notes: string[];
}

function fmt(n: number | null): string {
  return n === null ? "?" : String(n);
}

async function runBashSection(): Promise<{ rows: BashRow[]; failures: number }> {
  const rules = await loadRuleIds();
  const dirs = await listFixtureDirs();

  const relPath = (p: string) =>
    p.startsWith(REPO_ROOT + "/") ? p.slice(REPO_ROOT.length + 1) : p;

  // One batched run over every fixture keeps the bash pass's expensive
  // per-rule glob expansion from multiplying across N fixtures.
  const fixtureFiles: string[] = [];
  for (const id of dirs) {
    fixtureFiles.push(relPath(`${FIXTURES_ROOT}/${id}/fail.sh`));
    fixtureFiles.push(relPath(`${FIXTURES_ROOT}/${id}/pass.sh`));
  }
  let hits: Map<string, Map<string, number>> | null = null;
  let batchError: string | null = null;
  try {
    hits = await collectBashHits(fixtureFiles);
  } catch (e) {
    batchError = e instanceof Error ? e.message : String(e);
  }

  const rows: BashRow[] = [];
  for (const id of dirs) {
    const ruleName = rules.get(id) ?? "(unknown)";
    const failRel = relPath(`${FIXTURES_ROOT}/${id}/fail.sh`);
    const passRel = relPath(`${FIXTURES_ROOT}/${id}/pass.sh`);
    const notes: string[] = [];

    if (!rules.has(id)) {
      notes.push("no matching rule in rules.yaml");
    }

    let failExpected: number | null = null;
    try {
      failExpected = await expectedHits(`${REPO_ROOT}/${failRel}`);
      if (failExpected === null) {
        notes.push("fail.sh missing `# expect-hits: N` header");
      }
    } catch {
      notes.push("fail.sh unreadable or missing");
    }

    if (batchError) {
      notes.push(`batched bash run error: ${batchError}`);
    }

    const failActual = hits?.get(failRel)?.get(id) ?? 0;
    const passActual = hits?.get(passRel)?.get(id) ?? 0;

    const failOk = failExpected !== null && failActual === failExpected;
    const passOk = passActual === 0;
    if (!failOk && failExpected !== null) {
      notes.push(`fail.sh expected ${failExpected} hits, got ${failActual}`);
    }
    if (!passOk) {
      notes.push(`pass.sh expected 0 hits, got ${passActual}`);
    }

    rows.push({
      ruleId: id,
      ruleName,
      failExpected,
      failActual,
      passActual,
      ok: failOk && passOk && rules.has(id) && !batchError,
      notes,
    });
  }

  // Detect rules in rules.yaml with no fixture — that is a gap worth
  // flagging in the harness output.
  for (const [id, name] of rules) {
    if (!dirs.includes(id)) {
      rows.push({
        ruleId: id,
        ruleName: name,
        failExpected: null,
        failActual: 0,
        passActual: 0,
        ok: false,
        notes: ["no fixture directory"],
      });
    }
  }

  rows.sort((a, b) => a.ruleId.localeCompare(b.ruleId));
  const failures = rows.filter((r) => !r.ok).length;
  return { rows, failures };
}

function printBashSection(rows: BashRow[]) {
  console.log("== Bash rules pass ==");
  const header = [
    "Rule".padEnd(10),
    "Name".padEnd(22),
    "fail exp".padEnd(9),
    "fail got".padEnd(9),
    "pass got".padEnd(9),
    "result",
  ].join(" ");
  console.log(header);
  console.log("-".repeat(header.length));
  for (const r of rows) {
    const result = r.ok ? "PASS" : "FAIL";
    console.log(
      [
        r.ruleId.padEnd(10),
        r.ruleName.padEnd(22),
        fmt(r.failExpected).padEnd(9),
        String(r.failActual).padEnd(9),
        String(r.passActual).padEnd(9),
        result,
      ].join(" "),
    );
    for (const n of r.notes) {
      console.log(`  - ${n}`);
    }
  }
  console.log();
}

// ── Compose section ──────────────────────────────────────────────────────────

interface ComposeRow {
  rule: string;
  failExpected: number | null;
  failActual: number;
  passActual: number;
  ok: boolean;
  notes: string[];
}

const COMPOSE_GLOB = ".scripts/lint/fixtures/compose/**/*.yml";

// Single batched run over every compose fixture; result keyed by repo-rel
// path, then by rule name → count. Mirrors the bash-section optimisation.
async function collectComposeHits(files: string[]): Promise<Map<string, Map<string, number>>> {
  const findings = await runCompose({
    root: REPO_ROOT,
    fileFilter: files,
    globPattern: COMPOSE_GLOB,
  });
  const out = new Map<string, Map<string, number>>();
  for (const f of files) out.set(f, new Map());
  for (const f of findings) {
    const bucket = out.get(f.file);
    if (!bucket) continue;
    bucket.set(f.rule, (bucket.get(f.rule) ?? 0) + 1);
  }
  return out;
}

async function listComposeFixtureDirs(): Promise<string[]> {
  const dirs: string[] = [];
  try {
    for await (const entry of Deno.readDir(COMPOSE_FIXTURES_ROOT)) {
      if (entry.isDirectory) dirs.push(entry.name);
    }
  } catch {
    // Directory may not exist — caller renders an empty section.
  }
  dirs.sort();
  return dirs;
}

async function runComposeSection(): Promise<{ rows: ComposeRow[]; failures: number }> {
  const dirs = await listComposeFixtureDirs();
  const rows: ComposeRow[] = [];

  const relPath = (p: string) =>
    p.startsWith(REPO_ROOT + "/") ? p.slice(REPO_ROOT.length + 1) : p;

  const fixtureFiles: string[] = [];
  for (const dir of dirs) {
    fixtureFiles.push(relPath(`${COMPOSE_FIXTURES_ROOT}/${dir}/fail.yml`));
    fixtureFiles.push(relPath(`${COMPOSE_FIXTURES_ROOT}/${dir}/pass.yml`));
  }
  let hits: Map<string, Map<string, number>> | null = null;
  let batchError: string | null = null;
  try {
    if (fixtureFiles.length > 0) hits = await collectComposeHits(fixtureFiles);
  } catch (e) {
    batchError = e instanceof Error ? e.message : String(e);
  }

  for (const dir of dirs) {
    const failRel = relPath(`${COMPOSE_FIXTURES_ROOT}/${dir}/fail.yml`);
    const passRel = relPath(`${COMPOSE_FIXTURES_ROOT}/${dir}/pass.yml`);
    const notes: string[] = [];

    let expectedRuleName: string | null = null;
    try {
      expectedRuleName = await expectedRule(`${REPO_ROOT}/${failRel}`);
      if (expectedRuleName === null) notes.push("fail.yml missing `# expect-rule: <name>` header");
    } catch {
      notes.push("fail.yml unreadable or missing");
    }
    if (expectedRuleName && expectedRuleName !== dir) {
      notes.push(`fail.yml expect-rule "${expectedRuleName}" disagrees with directory name "${dir}"`);
    }

    let failExpected: number | null = null;
    try {
      failExpected = await expectedHits(`${REPO_ROOT}/${failRel}`);
      if (failExpected === null) notes.push("fail.yml missing `# expect-hits: N` header");
    } catch {
      // Already logged above.
    }

    const targetRule = expectedRuleName ?? dir;

    if (batchError) notes.push(`batched compose run error: ${batchError}`);

    const failActual = hits?.get(failRel)?.get(targetRule) ?? 0;
    const passActual = hits?.get(passRel)?.get(targetRule) ?? 0;

    const failOk = failExpected !== null && failActual === failExpected && failActual > 0;
    const passOk = passActual === 0;
    if (failExpected !== null && failActual !== failExpected) {
      notes.push(`fail.yml expected ${failExpected} hits, got ${failActual}`);
    } else if (failExpected !== null && failActual === 0) {
      notes.push("fail.yml produced no findings of the expected rule");
    }
    if (!passOk) {
      notes.push(`pass.yml expected 0 hits, got ${passActual}`);
    }

    rows.push({
      rule: targetRule,
      failExpected,
      failActual,
      passActual,
      ok: failOk && passOk && expectedRuleName !== null && !batchError,
      notes,
    });
  }

  rows.sort((a, b) => a.rule.localeCompare(b.rule));
  const failures = rows.filter((r) => !r.ok).length;
  return { rows, failures };
}

function printComposeSection(rows: ComposeRow[]) {
  console.log("== Compose pass ==");
  if (rows.length === 0) {
    console.log("(no compose fixtures found at .scripts/lint/fixtures/compose/)");
    console.log();
    return;
  }
  const header = [
    "Rule".padEnd(26),
    "fail exp".padEnd(9),
    "fail got".padEnd(9),
    "pass got".padEnd(9),
    "result",
  ].join(" ");
  console.log(header);
  console.log("-".repeat(header.length));
  for (const r of rows) {
    const result = r.ok ? "PASS" : "FAIL";
    console.log(
      [
        r.rule.padEnd(26),
        fmt(r.failExpected).padEnd(9),
        String(r.failActual).padEnd(9),
        String(r.passActual).padEnd(9),
        result,
      ].join(" "),
    );
    for (const n of r.notes) {
      console.log(`  - ${n}`);
    }
  }
  console.log();
}

// ── Shellcheck section ───────────────────────────────────────────────────────

interface ShellcheckRow {
  status: "PASS" | "SKIP" | "FAIL";
  notes: string[];
}

async function shellcheckAvailable(): Promise<boolean> {
  try {
    const p = new Deno.Command("shellcheck", {
      args: ["--version"],
      stdout: "null",
      stderr: "null",
    });
    const { code } = await p.output();
    return code === 0;
  } catch {
    return false;
  }
}

async function runShellcheckSection(): Promise<{ row: ShellcheckRow; failure: boolean }> {
  const notes: string[] = [];
  if (!(await shellcheckAvailable())) {
    notes.push(
      "shellcheck binary not on PATH; install it (apt: shellcheck, dnf: ShellCheck, brew: shellcheck) to exercise this section.",
    );
    return { row: { status: "SKIP", notes }, failure: false };
  }

  const failRel = ".scripts/lint/fixtures/shellcheck/fail.sh";
  const passRel = ".scripts/lint/fixtures/shellcheck/pass.sh";

  let failFindings: Finding[] = [];
  let passFindings: Finding[] = [];
  try {
    failFindings = await runShellcheck({
      root: REPO_ROOT,
      globs: [failRel],
      fileFilter: [failRel],
      severity: "info",
    });
  } catch (e) {
    notes.push(`fail.sh run error: ${e instanceof Error ? e.message : e}`);
  }
  try {
    passFindings = await runShellcheck({
      root: REPO_ROOT,
      globs: [passRel],
      fileFilter: [passRel],
      severity: "info",
    });
  } catch (e) {
    notes.push(`pass.sh run error: ${e instanceof Error ? e.message : e}`);
  }

  const targetRule = "SC2086";
  const failHits = failFindings.filter((f) => f.rule === targetRule).length;
  const passHits = passFindings.filter((f) => f.rule === targetRule).length;

  if (failHits === 0) {
    notes.push(`fail.sh expected at least one ${targetRule} finding, got 0`);
  }
  if (passHits !== 0) {
    notes.push(`pass.sh expected 0 ${targetRule} findings, got ${passHits}`);
  }

  const ok = failHits > 0 && passHits === 0;
  return { row: { status: ok ? "PASS" : "FAIL", notes }, failure: !ok };
}

function printShellcheckSection(row: ShellcheckRow) {
  console.log("== Shellcheck pass ==");
  console.log("Fixture                                       result");
  console.log("-".repeat(54));
  console.log(".scripts/lint/fixtures/shellcheck/{pass,fail}  ".padEnd(46) + row.status);
  for (const n of row.notes) {
    console.log(`  - ${n}`);
  }
  console.log();
}

// ── Orchestrator section ─────────────────────────────────────────────────────

interface OrchestratorRow {
  name: string;
  status: "PASS" | "FAIL";
  notes: string[];
}

async function runOrchestrator(args: string[]): Promise<{ code: number; stdout: string; stderr: string }> {
  const cmd = new Deno.Command("deno", {
    args: ["run", "-A", RUN_TS, ...args],
    cwd: REPO_ROOT,
    stdout: "piped",
    stderr: "piped",
  });
  const { code, stdout, stderr } = await cmd.output();
  return {
    code,
    stdout: new TextDecoder().decode(stdout),
    stderr: new TextDecoder().decode(stderr),
  };
}

async function runOrchestratorSection(): Promise<{ rows: OrchestratorRow[]; failures: number }> {
  // Run all three subprocess invocations in parallel — they're independent,
  // each deno boot costs ~3s of glob + type-check, and sequential would push
  // the harness past the 5-second budget.
  const [helpRes, failRes, passRes] = await Promise.all([
    runOrchestrator(["--help"]),
    runOrchestrator(["--rules", "--files", ".scripts/lint/fixtures/HARBOR001/fail.sh"]),
    runOrchestrator(["--rules", "--files", ".scripts/lint/fixtures/HARBOR001/pass.sh"]),
  ]);

  const rows: OrchestratorRow[] = [];

  {
    const notes: string[] = [];
    if (helpRes.code !== 0) notes.push(`--help exited ${helpRes.code}, expected 0`);
    const required = ["--shellcheck", "--rules", "--compose", "--files", "--json"];
    for (const flag of required) {
      if (!helpRes.stdout.includes(flag)) notes.push(`help text missing flag mention: ${flag}`);
    }
    rows.push({ name: "help-text", status: notes.length === 0 ? "PASS" : "FAIL", notes });
  }

  {
    const notes: string[] = [];
    if (failRes.code !== 1) notes.push(`fail fixture exited ${failRes.code}, expected 1`);
    rows.push({ name: "exit-code-fail", status: notes.length === 0 ? "PASS" : "FAIL", notes });
  }

  {
    const notes: string[] = [];
    if (passRes.code !== 0) notes.push(`pass fixture exited ${passRes.code}, expected 0`);
    rows.push({ name: "exit-code-pass", status: notes.length === 0 ? "PASS" : "FAIL", notes });
  }

  const failures = rows.filter((r) => r.status === "FAIL").length;
  return { rows, failures };
}

function printOrchestratorSection(rows: OrchestratorRow[]) {
  console.log("== Orchestrator ==");
  console.log("Check                  result");
  console.log("-".repeat(30));
  for (const r of rows) {
    console.log(`${r.name.padEnd(22)} ${r.status}`);
    for (const n of r.notes) {
      console.log(`  - ${n}`);
    }
  }
  console.log();
}

// ── Entry ────────────────────────────────────────────────────────────────────

async function main() {
  // Sections are independent; run in parallel so shellcheck + orchestrator
  // subprocess boots overlap with the bash glob expansion.
  const [bash, compose, shellcheck, orch] = await Promise.all([
    runBashSection(),
    runComposeSection(),
    runShellcheckSection(),
    runOrchestratorSection(),
  ]);

  printBashSection(bash.rows);
  printComposeSection(compose.rows);
  printShellcheckSection(shellcheck.row);
  printOrchestratorSection(orch.rows);

  const total = bash.failures + compose.failures + (shellcheck.failure ? 1 : 0) + orch.failures;
  if (total === 0) {
    const scNote = shellcheck.row.status === "SKIP" ? " (shellcheck SKIPPED)" : "";
    console.log(`self-test green: ${bash.rows.length} bash rule(s), ${compose.rows.length} compose rule(s), 1 shellcheck row, ${orch.rows.length} orchestrator check(s)${scNote}.`);
    Deno.exit(0);
  }
  console.log(`${total} self-test row(s) failed; see notes above.`);
  Deno.exit(1);
}

await main();
