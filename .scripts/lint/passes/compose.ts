/// <reference lib="deno.ns" />
/// <reference lib="dom" />

// Compose-file conventions pass.
//
// Ported from the former .scripts/lint.ts. Rules enforce Harbor's
// compose-file invariants (container naming, env_file, networks, volumes,
// build context, etc.). Output is lifted into the shared Finding shape so
// the orchestrator can treat all three passes uniformly.

import { expandGlob } from "https://deno.land/std/fs/mod.ts";
import { basename, join } from "https://deno.land/std/path/mod.ts";
import { parse as parseYaml } from "https://deno.land/std/yaml/mod.ts";

import type { Finding } from "../types.ts";
import { relative } from "../util.ts";

interface LintContext {
  filePath: string;
  relPath: string;
  parsed: Record<string, unknown>;
  handle: string;
  isCross: boolean;
  isNvidia: boolean;
  isVariant: boolean;
}

interface LintRule {
  name: string;
  check: (ctx: LintContext) => Finding[] | Promise<Finding[]>;
}

function extractHandle(filename: string): string {
  const stripped = filename.replace(/^compose\./, "").replace(/\.yml$/, "");
  if (stripped.startsWith("x.")) return stripped.replace(/^x\./, "").split(".")[0];
  return stripped.replace(/\.nvidia$/, "");
}

function isCrossFile(filename: string): boolean {
  return filename.startsWith("compose.x.");
}

function isNvidiaFile(filename: string): boolean {
  return filename.endsWith(".nvidia.yml");
}

function isVariantFile(filename: string): boolean {
  if (isCrossFile(filename) || isNvidiaFile(filename)) return false;
  const stripped = filename.replace(/^compose\./, "").replace(/\.yml$/, "");
  return stripped.includes(".");
}

function normalizeEnvFile(val: unknown): string[] | undefined {
  if (val === undefined || val === null) return undefined;
  if (typeof val === "string") return [val];
  if (Array.isArray(val)) return val.map(String);
  return undefined;
}

function finding(
  ctx: LintContext,
  rule: string,
  message: string,
  severity: "error" | "warning" = "error",
  service?: string,
): Finding {
  return {
    file: ctx.relPath,
    pass: "compose",
    rule,
    severity,
    message: service ? `[${service}] ${message}` : message,
  };
}

const rules: LintRule[] = [
  {
    name: "container-name",
    check(ctx) {
      const msgs: Finding[] = [];
      const services = (ctx.parsed.services as Record<string, Record<string, unknown>>) ?? {};
      for (const [name, svc] of Object.entries(services)) {
        if (!svc || typeof svc !== "object") continue;
        const cn = svc.container_name as string | undefined;
        if (!cn) {
          if (ctx.isCross || ctx.isNvidia) continue;
          msgs.push(finding(ctx, "container-name", "Missing container_name", "warning", name));
          continue;
        }
        const expected = `\${HARBOR_CONTAINER_PREFIX}.${name}`;
        if (cn !== expected) {
          msgs.push(
            finding(ctx, "container-name", `container_name is "${cn}", expected "${expected}"`, "error", name),
          );
        }
      }
      return msgs;
    },
  },
  {
    name: "env-file-main",
    check(ctx) {
      if (ctx.isCross || ctx.isNvidia) return [];
      const msgs: Finding[] = [];
      const services = (ctx.parsed.services as Record<string, Record<string, unknown>>) ?? {};
      for (const [name, svc] of Object.entries(services)) {
        if (!svc || typeof svc !== "object") continue;
        const envFile = normalizeEnvFile(svc.env_file);
        if (!envFile) {
          msgs.push(
            finding(ctx, "env-file-main", "Missing env_file (should include ./.env)", "warning", name),
          );
          continue;
        }
        if (!envFile.includes("./.env")) {
          msgs.push(finding(ctx, "env-file-main", `env_file does not include "./.env"`, "error", name));
        }
      }
      return msgs;
    },
  },
  {
    name: "env-file-override-path",
    check(ctx) {
      if (ctx.isCross || ctx.isNvidia) return [];
      const msgs: Finding[] = [];
      const services = (ctx.parsed.services as Record<string, Record<string, unknown>>) ?? {};
      for (const [name, svc] of Object.entries(services)) {
        if (!svc || typeof svc !== "object") continue;
        const envFile = normalizeEnvFile(svc.env_file);
        if (!envFile) continue;
        for (const ef of envFile) {
          if (ef === "./.env") continue;
          const overrideRe = /^\.\/services\/[\w-]+\/(override\.env|\.env)$/;
          if (!overrideRe.test(ef)) {
            msgs.push(
              finding(
                ctx,
                "env-file-override-path",
                `Unexpected env_file path "${ef}" — expected ./services/<handle>/override.env`,
                "warning",
                name,
              ),
            );
          }
        }
      }
      return msgs;
    },
  },
  {
    name: "volume-paths",
    check(ctx) {
      const msgs: Finding[] = [];
      const services = (ctx.parsed.services as Record<string, Record<string, unknown>>) ?? {};
      for (const [name, svc] of Object.entries(services)) {
        if (!svc || typeof svc !== "object") continue;
        const volumes = svc.volumes as (string | Record<string, unknown>)[] | undefined;
        if (!volumes) continue;
        for (const vol of volumes) {
          if (typeof vol !== "string") continue;
          if (vol.startsWith("/")) continue;
          const hostPath0 = vol.split(":")[0];
          if (hostPath0 && !hostPath0.includes("/") && !hostPath0.includes("\\")) continue;
          const hostPath = vol.split(":")[0];
          if (!hostPath) continue;
          if (hostPath.startsWith("${HARBOR_")) continue;
          if (hostPath.startsWith("./services/")) continue;
          if (hostPath.startsWith("./shared/")) continue;
          if (hostPath.startsWith("./tests/")) continue;
          if (hostPath.startsWith("./docs")) continue;
          if (hostPath.startsWith("/var/") || hostPath.startsWith("/etc/")) continue;
          msgs.push(
            finding(
              ctx,
              "volume-paths",
              `Volume host path "${hostPath}" — expected ./services/*, ./shared/*, or \${HARBOR_*}`,
              "warning",
              name,
            ),
          );
        }
      }
      return msgs;
    },
  },
  {
    name: "build-context",
    check(ctx) {
      const msgs: Finding[] = [];
      const services = (ctx.parsed.services as Record<string, Record<string, unknown>>) ?? {};
      for (const [name, svc] of Object.entries(services)) {
        if (!svc || typeof svc !== "object") continue;
        const build = svc.build as string | { context?: string } | undefined;
        if (!build) continue;
        const context = typeof build === "string" ? build : build.context;
        if (!context) continue;
        if (context.startsWith("./services/")) continue;
        if (context.startsWith("./tests/")) continue;
        if (context.startsWith("${HARBOR_")) continue;
        if (context.startsWith("https://")) continue;
        if (context === ".") continue;
        msgs.push(
          finding(
            ctx,
            "build-context",
            `Build context "${context}" — expected ./services/<dir>, \${HARBOR_*}, or remote URL`,
            "error",
            name,
          ),
        );
      }
      return msgs;
    },
  },
  {
    name: "network",
    check(ctx) {
      if (ctx.isCross || ctx.isNvidia) return [];
      if (ctx.parsed.networks) return [];
      const msgs: Finding[] = [];
      const services = (ctx.parsed.services as Record<string, Record<string, unknown>>) ?? {};
      for (const [name, svc] of Object.entries(services)) {
        if (!svc || typeof svc !== "object") continue;
        if (svc.network_mode) continue;
        if (!svc.ports && !svc.depends_on && !svc.networks) continue;
        const networks = svc.networks as string[] | Record<string, unknown> | undefined;
        if (!networks) {
          msgs.push(
            finding(ctx, "network", "Missing networks — should include harbor-network", "warning", name),
          );
          continue;
        }
        const netList = Array.isArray(networks) ? networks : Object.keys(networks);
        if (!netList.includes("harbor-network")) {
          msgs.push(finding(ctx, "network", "Networks does not include harbor-network", "warning", name));
        }
      }
      return msgs;
    },
  },
  {
    name: "port-variables",
    check(ctx) {
      if (ctx.isCross || ctx.isNvidia) return [];
      const msgs: Finding[] = [];
      const services = (ctx.parsed.services as Record<string, Record<string, unknown>>) ?? {};
      for (const [name, svc] of Object.entries(services)) {
        if (!svc || typeof svc !== "object") continue;
        const ports = svc.ports as (string | number)[] | undefined;
        if (!ports) continue;
        for (const port of ports) {
          const portStr = String(port);
          const hostPart = portStr.split(":")[0];
          if (hostPart && !hostPart.includes("${HARBOR_")) {
            msgs.push(
              finding(
                ctx,
                "port-variables",
                `Port mapping "${portStr}" uses a hardcoded host port — use \${HARBOR_*_HOST_PORT}`,
                "error",
                name,
              ),
            );
          }
        }
      }
      return msgs;
    },
  },
  {
    name: "service-name-match",
    check(ctx) {
      if (ctx.isCross || ctx.isNvidia || ctx.isVariant) return [];
      const services = (ctx.parsed.services as Record<string, unknown>) ?? {};
      const serviceNames = Object.keys(services);
      if (!serviceNames.includes(ctx.handle)) {
        return [
          finding(
            ctx,
            "service-name-match",
            `No service named "${ctx.handle}" — found: ${serviceNames.join(", ")}`,
            "warning",
          ),
        ];
      }
      return [];
    },
  },
  {
    name: "service-dir",
    async check(ctx) {
      if (ctx.isCross || ctx.isNvidia || ctx.isVariant) return [];
      const msgs: Finding[] = [];
      let actualDir = ctx.handle;
      const services = (ctx.parsed.services as Record<string, Record<string, unknown>>) ?? {};
      const primarySvc = services[ctx.handle];
      if (primarySvc && typeof primarySvc === "object") {
        const envFiles = normalizeEnvFile(primarySvc.env_file);
        if (envFiles) {
          for (const ef of envFiles) {
            const m = ef.match(/^\.\/services\/([\w-]+)\//);
            if (m && m[1] !== ctx.handle) {
              actualDir = m[1];
              break;
            }
          }
        }
        if (actualDir === ctx.handle) {
          const build = primarySvc.build as string | { context?: string } | undefined;
          const context = build && (typeof build === "string" ? build : build.context);
          if (context) {
            const m = context.match(/^\.\/services\/([\w-]+)/);
            if (m) actualDir = m[1];
          }
        }
      }
      const root = Deno.cwd();
      const dirPath = join(root, "services", actualDir);
      const overridePath = join(dirPath, "override.env");
      try {
        const stat = await Deno.stat(dirPath);
        if (!stat.isDirectory) {
          msgs.push(finding(ctx, "service-dir", `services/${actualDir} exists but is not a directory`));
          return msgs;
        }
      } catch {
        msgs.push(finding(ctx, "service-dir", `Missing directory services/${actualDir}/`, "warning"));
        return msgs;
      }
      try {
        await Deno.stat(overridePath);
      } catch {
        msgs.push(finding(ctx, "service-dir", `Missing services/${actualDir}/override.env`, "warning"));
      }
      return msgs;
    },
  },
];

async function lintFile(root: string, filePath: string): Promise<Finding[]> {
  const relPath = relative(root, filePath);
  const filename = basename(filePath);
  let raw: string;
  try {
    raw = await Deno.readTextFile(filePath);
  } catch {
    return [{ file: relPath, pass: "compose", rule: "read", severity: "error", message: "Could not read file" }];
  }
  let parsed: Record<string, unknown>;
  try {
    parsed = parseYaml(raw) as Record<string, unknown>;
  } catch (e) {
    return [{
      file: relPath,
      pass: "compose",
      rule: "yaml-parse",
      severity: "error",
      message: `Invalid YAML: ${e instanceof Error ? e.message : e}`,
    }];
  }
  if (!parsed || typeof parsed !== "object") {
    return [{
      file: relPath,
      pass: "compose",
      rule: "yaml-parse",
      severity: "error",
      message: "YAML did not parse to an object",
    }];
  }
  const ctx: LintContext = {
    filePath,
    relPath,
    parsed,
    handle: extractHandle(filename),
    isCross: isCrossFile(filename),
    isNvidia: isNvidiaFile(filename),
    isVariant: isVariantFile(filename),
  };
  const findings: Finding[] = [];
  for (const rule of rules) {
    findings.push(...(await rule.check(ctx)));
  }
  return findings;
}

export interface ComposeOptions {
  root: string;
  fileFilter?: string[] | null;
  composeGlob?: string; // e.g. "compose.*.yml"
  // Full glob pattern relative to `root` (or absolute), bypassing the default
  // services/<composeGlob> layout. Used by the self-test harness so fixtures
  // can live outside services/.
  globPattern?: string;
}

export async function runCompose(opts: ComposeOptions): Promise<Finding[]> {
  const pattern = opts.globPattern
    ? (opts.globPattern.startsWith("/") ? opts.globPattern : join(opts.root, opts.globPattern))
    : join(opts.root, "services", opts.composeGlob ?? "compose.*.yml");
  const files: string[] = [];
  for await (const entry of expandGlob(pattern)) {
    if (entry.isFile) files.push(entry.path);
  }
  files.sort();
  const findings: Finding[] = [];
  for (const f of files) {
    const rel = relative(opts.root, f);
    if (opts.fileFilter && !opts.fileFilter.includes(rel)) continue;
    findings.push(...(await lintFile(opts.root, f)));
  }
  return findings;
}
