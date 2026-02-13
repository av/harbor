#!/usr/bin/env -S deno run -A

import { getOptionalValue, setValue } from "../routines/envManager.ts";

interface MigrationContext {
  envPath: string;
  dryRun: boolean;
  log: (message: string) => void;
  getEnvValue: (key: string) => Promise<string | undefined>;
  setEnvValue: (key: string, value: string) => Promise<void>;
}

interface MigrationModule {
  up: (context: MigrationContext) => Promise<void>;
}

const BASELINE_VERSION = "0.4.1";
const MIGRATIONS_DIR = ".scripts/migrations";

type CliArgs = {
  dryRun: boolean;
  targetVersion?: string;
  help: boolean;
};

function parseArgs(args: string[]): CliArgs {
  const parsed: CliArgs = { dryRun: false, help: false };

  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];

    if (arg === "--dry-run") {
      parsed.dryRun = true;
      continue;
    }

    if (arg === "-h" || arg === "--help" || arg === "help") {
      parsed.help = true;
      continue;
    }

    if (arg === "--target" && args[index + 1]) {
      parsed.targetVersion = args[index + 1];
      index += 1;
      continue;
    }

    if (arg.startsWith("--target=")) {
      parsed.targetVersion = arg.split("=")[1];
      continue;
    }

    throw new Error(`Unknown argument: ${arg}`);
  }

  return parsed;
}

function parseSemver(version: string): [number, number, number] {
  const match = version.match(/^(\d+)\.(\d+)\.(\d+)$/);

  if (!match) {
    throw new Error(`Invalid semver version: ${version}`);
  }

  return [Number(match[1]), Number(match[2]), Number(match[3])];
}

function compareSemver(left: string, right: string): number {
  const leftParts = parseSemver(left);
  const rightParts = parseSemver(right);

  for (let index = 0; index < 3; index += 1) {
    const delta = leftParts[index] - rightParts[index];

    if (delta !== 0) {
      return delta;
    }
  }

  return 0;
}

async function updateConfigVersion(
  context: MigrationContext,
  nextVersion: string,
): Promise<void> {
  if (!context.dryRun) {
    await context.setEnvValue("config.version", nextVersion);
  }
}

async function listMigrationVersions(): Promise<string[]> {
  const versions: string[] = [];

  for await (const entry of Deno.readDir(MIGRATIONS_DIR)) {
    if (!entry.isFile || !entry.name.endsWith(".ts")) {
      continue;
    }

    const version = entry.name.replace(/\.ts$/, "");
    parseSemver(version);
    versions.push(version);
  }

  return versions.sort(compareSemver);
}

function selectMigrations(
  versions: string[],
  currentVersion: string,
  targetVersion: string,
): string[] {
  return versions.filter((version) => {
    return compareSemver(version, currentVersion) > 0 &&
      compareSemver(version, targetVersion) <= 0;
  });
}

function usage(): void {
  console.log("Harbor migration runner");
  console.log("");
  console.log("Usage: harbor migrate [--dry-run] [--target <version>]");
  console.log("");
  console.log("Options:");
  console.log("  --dry-run           Preview migrations without writing files");
  console.log("  --target <version>  Target Harbor version (defaults to current CLI version)");
  console.log("  -h, --help          Show this help message");
}

async function main(): Promise<void> {
  const args = parseArgs(Deno.args);

  if (args.help) {
    usage();
    return;
  }

  if (!args.targetVersion) {
    throw new Error("Target version is required. Pass --target <version>.");
  }

  parseSemver(args.targetVersion);

  const envPath = ".env";
  const context: MigrationContext = {
    envPath,
    dryRun: args.dryRun,
    log: (message: string) => {
      console.log(`${args.dryRun ? "[dry-run] " : ""}${message}`);
    },
    getEnvValue: async (key: string) => {
      return await getOptionalValue({ key, profile: envPath });
    },
    setEnvValue: async (key: string, value: string) => {
      await setValue({ key, value, profile: envPath });
    },
  };

  const currentVersion = await context.getEnvValue("config.version") ?? BASELINE_VERSION;

  parseSemver(currentVersion);

  if (compareSemver(currentVersion, args.targetVersion) > 0) {
    throw new Error(
      `Current config version ${currentVersion} is newer than target ${args.targetVersion}.`,
    );
  }

  const availableMigrations = await listMigrationVersions();
  const migrations = selectMigrations(availableMigrations, currentVersion, args.targetVersion);

  if (migrations.length === 0) {
    console.log(`Config is up to date (${currentVersion}).`);
    return;
  }

  console.log(
    `${args.dryRun ? "[dry-run] " : ""}Applying migrations ${currentVersion} -> ${args.targetVersion}`,
  );

  for (const migrationVersion of migrations) {
    console.log(`${args.dryRun ? "[dry-run] " : ""}Running ${migrationVersion}`);

    const modulePath = new URL(`./migrations/${migrationVersion}.ts`, import.meta.url).href;
    const migration = await import(modulePath) as MigrationModule;

    await migration.up(context);

    await updateConfigVersion(context, migrationVersion);
  }

  console.log(
    `${args.dryRun ? "[dry-run] " : ""}Migration complete. Config version: ${migrations[migrations.length - 1]}`,
  );
}

main().catch((error) => {
  console.error(`[migrate] ${error.message}`);
  Deno.exit(1);
});
