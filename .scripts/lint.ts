// harbor dev lint [--fix] [--filter <glob>]
// Lints compose files in services/ against Harbor conventions.

import { parse } from "https://deno.land/std/flags/mod.ts";
import { expandGlob } from "https://deno.land/std/fs/mod.ts";
import { basename, join } from "https://deno.land/std/path/mod.ts";
import { parse as parseYaml } from "https://deno.land/std/yaml/mod.ts";

// -------------------------------------------------------------------
// Types
// -------------------------------------------------------------------

interface LintMessage {
  file: string;
  service?: string;
  rule: string;
  severity: "error" | "warning";
  message: string;
}

interface LintRule {
  name: string;
  description: string;
  check: (ctx: LintContext) => LintMessage[] | Promise<LintMessage[]>;
}

interface LintContext {
  /** Absolute path to the compose file */
  filePath: string;
  /** Relative path from harbor root (for display) */
  relPath: string;
  /** Parsed YAML content */
  parsed: Record<string, any>;
  /** Service handle extracted from filename */
  handle: string;
  /** Whether this is a cross-service file (compose.x.*) */
  isCross: boolean;
  /** Whether this is an nvidia file (compose.*.nvidia.yml) */
  isNvidia: boolean;
  /** Whether this is a variant file (compose.service.variant.yml) */
  isVariant: boolean;
  /** Raw file content */
  raw: string;
}

// -------------------------------------------------------------------
// Helpers
// -------------------------------------------------------------------

const HARBOR_ROOT = Deno.cwd();

function extractHandle(filename: string): string {
  // compose.x.service1.service2.yml -> service1
  // compose.service.yml -> service
  // compose.service.nvidia.yml -> service
  const stripped = filename
    .replace(/^compose\./, "")
    .replace(/\.yml$/, "");

  if (stripped.startsWith("x.")) {
    // cross-service: return first service
    return stripped.replace(/^x\./, "").split(".")[0];
  }
  // nvidia or other variant
  return stripped.replace(/\.nvidia$/, "");
}

function isCrossFile(filename: string): boolean {
  return filename.startsWith("compose.x.");
}

function isNvidiaFile(filename: string): boolean {
  return filename.endsWith(".nvidia.yml");
}

/** Whether this is a variant file (e.g. compose.searxng.morphic.yml — not cross-service, but a config variant) */
function isVariantFile(filename: string): boolean {
  if (isCrossFile(filename) || isNvidiaFile(filename)) return false;
  const stripped = filename.replace(/^compose\./, "").replace(/\.yml$/, "");
  return stripped.includes(".");
}

/** Normalize env_file to always be an array (handles string | string[] | undefined) */
function normalizeEnvFile(val: unknown): string[] | undefined {
  if (val === undefined || val === null) return undefined;
  if (typeof val === "string") return [val];
  if (Array.isArray(val)) return val.map(String);
  return undefined;
}

function msg(
  ctx: LintContext,
  rule: string,
  message: string,
  service?: string,
  severity: "error" | "warning" = "error",
): LintMessage {
  return { file: ctx.relPath, service, rule, severity, message };
}

// -------------------------------------------------------------------
// Lint rules
// -------------------------------------------------------------------

const rules: LintRule[] = [];

// 1. container_name must use ${HARBOR_CONTAINER_PREFIX}.<handle>
rules.push({
  name: "container-name",
  description: "container_name must be ${HARBOR_CONTAINER_PREFIX}.<service>",
  check(ctx) {
    const msgs: LintMessage[] = [];
    const services = ctx.parsed.services ?? {};

    for (const [name, svc] of Object.entries<any>(services)) {
      if (!svc || typeof svc !== "object") continue;

      const cn = svc.container_name;
      if (!cn) {
        // Cross-service files often only add overrides, skip
        if (ctx.isCross || ctx.isNvidia) continue;
        msgs.push(
          msg(ctx, this.name, `Missing container_name`, name, "warning"),
        );
        continue;
      }

      const expected = `\${HARBOR_CONTAINER_PREFIX}.${name}`;
      if (cn !== expected) {
        msgs.push(
          msg(
            ctx,
            this.name,
            `container_name is "${cn}", expected "${expected}"`,
            name,
          ),
        );
      }
    }
    return msgs;
  },
});

// 2. env_file must include ./.env (main files only)
rules.push({
  name: "env-file-main",
  description: "env_file must include ./.env",
  check(ctx) {
    if (ctx.isCross || ctx.isNvidia) return [];
    const msgs: LintMessage[] = [];
    const services = ctx.parsed.services ?? {};

    for (const [name, svc] of Object.entries<any>(services)) {
      if (!svc || typeof svc !== "object") continue;
      const envFile = normalizeEnvFile(svc.env_file);
      if (!envFile) {
        msgs.push(
          msg(ctx, this.name, `Missing env_file (should include ./.env)`, name, "warning"),
        );
        continue;
      }
      if (!envFile.includes("./.env")) {
        msgs.push(
          msg(ctx, this.name, `env_file does not include "./.env"`, name),
        );
      }
    }
    return msgs;
  },
});

// 3. env_file override path must use ./services/<dir>/override.env
rules.push({
  name: "env-file-override-path",
  description: "Override env_file must point to ./services/<dir>/override.env",
  check(ctx) {
    if (ctx.isCross || ctx.isNvidia) return [];
    const msgs: LintMessage[] = [];
    const services = ctx.parsed.services ?? {};

    for (const [name, svc] of Object.entries<any>(services)) {
      if (!svc || typeof svc !== "object") continue;
      const envFile = normalizeEnvFile(svc.env_file);
      if (!envFile) continue;

      for (const ef of envFile) {
        if (ef === "./.env") continue;
        // Must match ./services/<something>/override.env or ./services/<something>/.env
        const overrideRe = /^\.\/services\/[\w-]+\/(override\.env|\.env)$/;
        if (!overrideRe.test(ef)) {
          msgs.push(
            msg(
              ctx,
              this.name,
              `Unexpected env_file path "${ef}" — expected ./services/<handle>/override.env`,
              name,
              "warning",
            ),
          );
        }
      }
    }
    return msgs;
  },
});

// 4. Volume mount local paths should be relative and start with ./services/ or ${HARBOR_
rules.push({
  name: "volume-paths",
  description: "Volume mounts must use ./services/ or ${HARBOR_*} for local paths",
  check(ctx) {
    const msgs: LintMessage[] = [];
    const services = ctx.parsed.services ?? {};

    for (const [name, svc] of Object.entries<any>(services)) {
      if (!svc || typeof svc !== "object") continue;
      const volumes: (string | Record<string, any>)[] | undefined = svc.volumes;
      if (!volumes) continue;

      for (const vol of volumes) {
        if (typeof vol !== "string") continue;

        // In-container path override (e.g. /boost/.venv)
        if (vol.startsWith("/")) continue;

        // Docker named volume (e.g. openfang_data:/data) — no path separators in host part
        const hostPath0 = vol.split(":")[0];
        if (hostPath0 && !hostPath0.includes("/") && !hostPath0.includes("\\")) continue;

        const hostPath = vol.split(":")[0];
        if (!hostPath) continue;

        // Valid prefixes
        if (hostPath.startsWith("${HARBOR_")) continue;
        if (hostPath.startsWith("./services/")) continue;
        if (hostPath.startsWith("./shared/")) continue;
        if (hostPath.startsWith("./integration/")) continue;
        // Project-root relative paths (e.g. ./docs for landing page)
        if (hostPath.startsWith("./docs")) continue;
        // System mounts like /var/run/docker.sock, /etc/localtime
        if (hostPath.startsWith("/var/") || hostPath.startsWith("/etc/")) continue;

        // Catch paths like ./litellm/ (missing services/ prefix)
        // or absolute paths to project dirs
        msgs.push(
          msg(
            ctx,
            this.name,
            `Volume host path "${hostPath}" — expected ./services/*, ./shared/*, or \${HARBOR_*}`,
            name,
            "warning",
          ),
        );
      }
    }
    return msgs;
  },
});

// 5. Build context should point to ./services/<handle> or use a variable
rules.push({
  name: "build-context",
  description: "Build context must be ./services/<dir> or a ${HARBOR_*} variable",
  check(ctx) {
    const msgs: LintMessage[] = [];
    const services = ctx.parsed.services ?? {};

    for (const [name, svc] of Object.entries<any>(services)) {
      if (!svc || typeof svc !== "object") continue;
      const build = svc.build;
      if (!build) continue;

      const context = typeof build === "string" ? build : build.context;
      if (!context) continue;

      // Allow: ./services/*, ./integration/*, ${HARBOR_*}, https://*.git*, "." (monorepo-style)
      if (context.startsWith("./services/")) continue;
      if (context.startsWith("./integration/")) continue;
      if (context.startsWith("${HARBOR_")) continue;
      if (context.startsWith("https://")) continue;
      if (context === ".") continue;

      msgs.push(
        msg(
          ctx,
          this.name,
          `Build context "${context}" — expected ./services/<dir>, \${HARBOR_*}, or remote URL`,
          name,
        ),
      );
    }
    return msgs;
  },
});

// 6. Services should connect to harbor-network (main files only)
rules.push({
  name: "network",
  description: "Services should include harbor-network",
  check(ctx) {
    if (ctx.isCross || ctx.isNvidia) return [];
    // Files defining custom top-level networks use their own networking intentionally
    if (ctx.parsed.networks) return [];
    const msgs: LintMessage[] = [];
    const services = ctx.parsed.services ?? {};

    for (const [name, svc] of Object.entries<any>(services)) {
      if (!svc || typeof svc !== "object") continue;
      // network_mode (e.g. "host") is mutually exclusive with networks
      if (svc.network_mode) continue;
      // Services without ports or depends_on are likely CLI tools, not networked services
      if (!svc.ports && !svc.depends_on && !svc.networks) continue;
      const networks = svc.networks;
      if (!networks) {
        msgs.push(
          msg(ctx, this.name, `Missing networks — should include harbor-network`, name, "warning"),
        );
        continue;
      }
      const netList = Array.isArray(networks) ? networks : Object.keys(networks);
      if (!netList.includes("harbor-network")) {
        msgs.push(
          msg(ctx, this.name, `Networks does not include harbor-network`, name, "warning"),
        );
      }
    }
    return msgs;
  },
});

// 7. Port mappings should use HARBOR_ variables for host ports
rules.push({
  name: "port-variables",
  description: "Host ports should use ${HARBOR_*_HOST_PORT} variables",
  check(ctx) {
    if (ctx.isCross || ctx.isNvidia) return [];
    const msgs: LintMessage[] = [];
    const services = ctx.parsed.services ?? {};

    for (const [name, svc] of Object.entries<any>(services)) {
      if (!svc || typeof svc !== "object") continue;
      const ports: (string | number)[] | undefined = svc.ports;
      if (!ports) continue;

      for (const port of ports) {
        const portStr = String(port);
        // Check that host side uses a variable
        const hostPart = portStr.split(":")[0];
        if (hostPart && !hostPart.includes("${HARBOR_")) {
          msgs.push(
            msg(
              ctx,
              this.name,
              `Port mapping "${portStr}" uses a hardcoded host port — use \${HARBOR_*_HOST_PORT}`,
              name,
            ),
          );
        }
      }
    }
    return msgs;
  },
});

// 8. Service name should match the handle from the filename (main files only)
rules.push({
  name: "service-name-match",
  description: "Primary service name should match the filename handle",
  check(ctx) {
    if (ctx.isCross || ctx.isNvidia || ctx.isVariant) return [];
    const msgs: LintMessage[] = [];
    const services = ctx.parsed.services ?? {};
    const serviceNames = Object.keys(services);

    // The handle should appear as one of the service names
    if (!serviceNames.includes(ctx.handle)) {
      msgs.push(
        msg(
          ctx,
          this.name,
          `No service named "${ctx.handle}" found — expected at least one service matching the filename handle. Found: ${serviceNames.join(", ")}`,
          undefined,
          "warning",
        ),
      );
    }
    return msgs;
  },
});

// 9. Service directory and override.env must exist
rules.push({
  name: "service-dir",
  description: "services/<handle>/ directory and override.env must exist",
  async check(ctx) {
    if (ctx.isCross || ctx.isNvidia || ctx.isVariant) return [];
    const msgs: LintMessage[] = [];

    // Determine actual service directory — prefer paths referenced in env_file/build,
    // fall back to the handle name
    let actualDir = ctx.handle;
    const services = ctx.parsed.services ?? {};
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
        const build = primarySvc.build;
        const context = build && (typeof build === "string" ? build : build.context);
        if (context) {
          const m = context.match(/^\.\/services\/([\w-]+)/);
          if (m) actualDir = m[1];
        }
      }
    }

    const dirPath = join(HARBOR_ROOT, "services", actualDir);
    const overridePath = join(dirPath, "override.env");

    try {
      const stat = await Deno.stat(dirPath);
      if (!stat.isDirectory) {
        msgs.push(
          msg(ctx, this.name, `services/${actualDir} exists but is not a directory`, undefined),
        );
        return msgs;
      }
    } catch {
      msgs.push(
        msg(ctx, this.name, `Missing directory services/${actualDir}/`, undefined, "warning"),
      );
      return msgs;
    }

    try {
      await Deno.stat(overridePath);
    } catch {
      msgs.push(
        msg(ctx, this.name, `Missing services/${actualDir}/override.env`, undefined, "warning"),
      );
    }

    return msgs;
  },
});

// -------------------------------------------------------------------
// Runner
// -------------------------------------------------------------------

async function lintFile(filePath: string): Promise<LintMessage[]> {
  const relPath = filePath.replace(HARBOR_ROOT + "/", "");
  const filename = basename(filePath);

  let raw: string;
  try {
    raw = await Deno.readTextFile(filePath);
  } catch {
    return [{ file: relPath, rule: "read", severity: "error", message: "Could not read file" }];
  }

  let parsed: Record<string, any>;
  try {
    parsed = parseYaml(raw) as Record<string, any>;
  } catch (e) {
    return [{ file: relPath, rule: "yaml-parse", severity: "error", message: `Invalid YAML: ${e.message}` }];
  }

  if (!parsed || typeof parsed !== "object") {
    return [{ file: relPath, rule: "yaml-parse", severity: "error", message: "YAML did not parse to an object" }];
  }

  const ctx: LintContext = {
    filePath,
    relPath,
    parsed,
    handle: extractHandle(filename),
    isCross: isCrossFile(filename),
    isNvidia: isNvidiaFile(filename),
    isVariant: isVariantFile(filename),
    raw,
  };

  const msgs: LintMessage[] = [];
  for (const rule of rules) {
    msgs.push(...await rule.check(ctx));
  }
  return msgs;
}

async function main() {
  const args = parse(Deno.args, {
    string: ["filter"],
    boolean: ["help", "list-rules"],
    default: { filter: "compose.*.yml" },
    alias: { h: "help", f: "filter" },
  });

  if (args.help) {
    console.log(`Usage: harbor dev lint [options]

Options:
  -f, --filter <glob>   Glob filter for compose files (default: compose.*.yml)
  --list-rules          List all lint rules
  -h, --help            Show this help

Examples:
  harbor dev lint
  harbor dev lint --filter "compose.ollama*"
  harbor dev lint --list-rules`);
    Deno.exit(0);
  }

  if (args["list-rules"]) {
    console.log("Available lint rules:\n");
    for (const rule of rules) {
      console.log(`  ${rule.name}`);
      console.log(`    ${rule.description}\n`);
    }
    Deno.exit(0);
  }

  const servicesDir = join(HARBOR_ROOT, "services");
  const pattern = join(servicesDir, args.filter);

  const files: string[] = [];
  for await (const entry of expandGlob(pattern)) {
    if (entry.isFile) files.push(entry.path);
  }
  files.sort();

  if (files.length === 0) {
    console.log(`No files matched "${args.filter}" in services/`);
    Deno.exit(0);
  }

  console.log(`Linting ${files.length} compose files...\n`);

  let totalErrors = 0;
  let totalWarnings = 0;
  const allMessages: LintMessage[] = [];

  for (const file of files) {
    const msgs = await lintFile(file);
    allMessages.push(...msgs);
    totalErrors += msgs.filter((m) => m.severity === "error").length;
    totalWarnings += msgs.filter((m) => m.severity === "warning").length;
  }

  // Group by file
  const byFile = new Map<string, LintMessage[]>();
  for (const m of allMessages) {
    const list = byFile.get(m.file) ?? [];
    list.push(m);
    byFile.set(m.file, list);
  }

  for (const [file, msgs] of byFile) {
    console.log(file);
    for (const m of msgs) {
      const sev = m.severity === "error" ? "ERR" : "WRN";
      const svcLabel = m.service ? ` [${m.service}]` : "";
      console.log(`  ${sev} ${m.rule}${svcLabel}: ${m.message}`);
    }
    console.log();
  }

  if (totalErrors === 0 && totalWarnings === 0) {
    console.log("All files passed.");
  } else {
    console.log(
      `Found ${totalErrors} error(s) and ${totalWarnings} warning(s) across ${byFile.size} file(s).`,
    );
  }

  Deno.exit(totalErrors > 0 ? 1 : 0);
}

await main();
