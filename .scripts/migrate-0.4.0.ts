#!/usr/bin/env -S deno run -A
// harbor migrate [--dry-run] [--force] [--rollback=<backup-dir>]
// Migration script for Harbor 0.4.0 services folder restructuring

import { parse } from "https://deno.land/std/flags/mod.ts";
import { join, basename } from "https://deno.land/std/path/mod.ts";
import { ensureDir, exists } from "https://deno.land/std/fs/mod.ts";

const EXCLUDE_DIRS = new Set([
  // Infrastructure directories - never migrate
  "app",
  "docs",
  "routines",
  "scripts",
  ".scripts",
  "profiles",
  "shared",
  "harbor",
  "tools",
  "skills",
  "services", // The target directory itself

  // Build and dependencies
  "node_modules",
  "dist",
  ".cache",
  ".local",
  ".npm",
  ".pkgx",
  ".parcel-cache",
  ".venv",

  // Git and version control
  ".git",
  ".github",

  // Hidden files and directories (general catch-all)
  // Will be checked with startsWith('.')
]);

const EXCLUDE_FILES = new Set([
  "compose.yml", // Base compose stays at root
  ".env", // Environment stays at root
]);

interface MigrationPlan {
  serviceDirs: string[];
  composeFiles: string[];
  needsMigration: boolean;
  renames: { from: string; to: string; type: 'dir' | 'file' }[];
}

interface MigrationResult {
  success: boolean;
  backupDir?: string;
  movedDirs: string[];
  movedFiles: string[];
  renamedItems: { from: string; to: string }[];
  errors: string[];
}

const colors = {
  reset: "\x1b[0m",
  bold: "\x1b[1m",
  red: "\x1b[31m",
  green: "\x1b[32m",
  yellow: "\x1b[33m",
  blue: "\x1b[34m",
  cyan: "\x1b[36m",
};

function log(level: string, message: string, ...args: any[]) {
  const timestamp = new Date().toLocaleTimeString();
  const prefix = `${timestamp} [${level}]`;

  switch (level) {
    case "ERROR":
      console.error(`${colors.red}${prefix} ${message}${colors.reset}`, ...args);
      break;
    case "WARN":
      console.warn(`${colors.yellow}${prefix} ${message}${colors.reset}`, ...args);
      break;
    case "SUCCESS":
      console.log(`${colors.green}${prefix} ${message}${colors.reset}`, ...args);
      break;
    case "INFO":
      console.log(`${colors.blue}${prefix} ${message}${colors.reset}`, ...args);
      break;
    default:
      console.log(`${prefix} ${message}`, ...args);
  }
}

async function isServiceDirectory(dir: string): Promise<boolean> {
  const dirName = basename(dir);

  // Check if there's a corresponding compose file
  const harborHome = Deno.cwd();

  // Special case: open-webui directory should be treated as a service directory
  // even though its compose files are named "webui"
  if (dirName === "open-webui") {
    const webuiComposeFile = join(harborHome, "compose.webui.yml");
    if (await exists(webuiComposeFile)) {
      return true;
    }
  }

  const possibleComposeFiles = [
    join(harborHome, `compose.${dirName}.yml`),
    join(harborHome, `compose.${dirName}.ts`),
    join(harborHome, "services", `compose.${dirName}.yml`),
    join(harborHome, "services", `compose.${dirName}.ts`),
  ];

  for (const composeFile of possibleComposeFiles) {
    if (await exists(composeFile)) {
      return true;
    }
  }

  return false;
}

async function detectOpenWebuiRenames(): Promise<{ from: string; to: string; type: 'dir' | 'file' }[]> {
  const harborHome = Deno.cwd();
  const renames: { from: string; to: string; type: 'dir' | 'file' }[] = [];

  // Only check for open-webui directory/files in services/ (already migrated)
  // Files at root will be handled during the move operation
  const servicesOpenWebui = join(harborHome, "services", "open-webui");
  if (await exists(servicesOpenWebui)) {
    try {
      const stat = await Deno.stat(servicesOpenWebui);
      if (stat.isDirectory) {
        renames.push({ from: "services/open-webui", to: "services/webui", type: 'dir' });
      }
    } catch {
      // Skip if can't stat
    }
  }

  // Check for compose files with open-webui in services/ directory
  const servicesDir = join(harborHome, "services");
  if (await exists(servicesDir)) {
    try {
      for await (const entry of Deno.readDir(servicesDir)) {
        if (entry.isFile && entry.name.includes("open-webui") && entry.name.match(/^compose\..+\.(yml|ts)$/)) {
          const newName = entry.name.replace(/open-webui/g, "webui");
          renames.push({
            from: `services/${entry.name}`,
            to: `services/${newName}`,
            type: 'file'
          });
        }
      }
    } catch {
      // Skip if can't read directory
    }
  }

  return renames;
}

async function detectMigration(): Promise<MigrationPlan> {
  const harborHome = Deno.cwd();
  const serviceDirs: string[] = [];
  const composeFiles: string[] = [];

  log("INFO", "Scanning Harbor directory for files to migrate...");

  // Scan root directory for service directories and compose files
  for await (const entry of Deno.readDir(harborHome)) {
    const entryPath = join(harborHome, entry.name);

    // Skip excluded directories and hidden files
    if (EXCLUDE_DIRS.has(entry.name) || entry.name.startsWith(".")) {
      continue;
    }

    // Check for service directories at root
    if (entry.isDirectory) {
      if (await isServiceDirectory(entryPath)) {
        serviceDirs.push(entry.name);
      }
    }

    // Check for compose files at root (except base compose.yml)
    if (entry.isFile && !EXCLUDE_FILES.has(entry.name)) {
      if (entry.name.match(/^compose\..+\.(yml|ts)$/)) {
        composeFiles.push(entry.name);
      }
    }
  }

  // Detect open-webui → webui renames
  const renames = await detectOpenWebuiRenames();

  const needsMigration = serviceDirs.length > 0 || composeFiles.length > 0 || renames.length > 0;

  return {
    serviceDirs,
    composeFiles,
    needsMigration,
    renames,
  };
}

async function checkPreflightConditions(): Promise<{ canProceed: boolean; warnings: string[] }> {
  const warnings: string[] = [];
  let canProceed = true;

  // Check if we're in a Harbor directory
  const harborHome = Deno.cwd();
  const harborShExists = await exists(join(harborHome, "harbor.sh"));

  if (!harborShExists) {
    log("ERROR", "Not in a Harbor directory. Please run this command from the Harbor root.");
    canProceed = false;
    return { canProceed, warnings };
  }

  // Check if services directory already exists and is populated
  const servicesDir = join(harborHome, "services");
  if (await exists(servicesDir)) {
    let hasContent = false;
    try {
      for await (const _ of Deno.readDir(servicesDir)) {
        hasContent = true;
        break;
      }
    } catch {
      // Directory might not be readable
    }

    if (hasContent) {
      log("INFO", "services/ directory already exists and contains files");
    }
  }

  // Check if there are running containers
  try {
    const process = new Deno.Command("docker", {
      args: ["ps", "--filter", "name=harbor", "--format", "{{.Names}}"],
      stdout: "piped",
    });

    const { stdout } = await process.output();
    const runningContainers = new TextDecoder().decode(stdout).trim();

    if (runningContainers) {
      warnings.push("Harbor services are currently running. Consider stopping them with 'harbor down' before migration.");
    }
  } catch {
    // Docker might not be available, skip this check
  }

  // Check for uncommitted git changes
  try {
    const process = new Deno.Command("git", {
      args: ["status", "--porcelain"],
      stdout: "piped",
      cwd: harborHome,
    });

    const { stdout } = await process.output();
    const changes = new TextDecoder().decode(stdout).trim();

    if (changes) {
      warnings.push("You have uncommitted changes. Consider committing or stashing them before migration.");
    }
  } catch {
    // Not a git repository or git not available
  }

  return { canProceed, warnings };
}

async function getDirSize(dirPath: string): Promise<number> {
  try {
    const command = new Deno.Command("du", {
      args: ["-sb", dirPath],
      stdout: "piped",
    });
    const { stdout } = await command.output();
    const output = new TextDecoder().decode(stdout);
    const size = parseInt(output.split("\t")[0]);
    return size;
  } catch {
    return 0;
  }
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(2)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

async function createBackup(plan: MigrationPlan): Promise<string> {
  const harborHome = Deno.cwd();
  const timestamp = Date.now();
  const backupDir = join(harborHome, `.migration-backup-${timestamp}`);

  // Check sizes of directories to be backed up
  log("INFO", "Checking directory sizes...");
  let totalSize = 0;
  const dirSizes: { dir: string; size: number }[] = [];

  for (const dir of plan.serviceDirs) {
    const srcPath = join(harborHome, dir);
    const size = await getDirSize(srcPath);
    totalSize += size;
    dirSizes.push({ dir, size });

    if (size > 100 * 1024 * 1024) { // > 100MB
      log("WARN", `  ${dir}/: ${formatBytes(size)}`);
    }
  }

  // Check sizes of directories that will be renamed
  for (const rename of plan.renames) {
    if (rename.type === 'dir') {
      const srcPath = join(harborHome, rename.from);
      const size = await getDirSize(srcPath);
      totalSize += size;

      if (size > 100 * 1024 * 1024) { // > 100MB
        log("WARN", `  ${rename.from}/: ${formatBytes(size)}`);
      }
    }
  }

  if (totalSize > 1024 * 1024 * 1024) { // > 1GB
    log("WARN", `Total backup size will be approximately ${formatBytes(totalSize)}`);
    log("WARN", "Large directories contain data files that won't be modified during migration.");
    log("INFO", "Migration only moves directories, so you can skip backup with --no-backup flag.");
    log("INFO", "If migration fails, you can manually move directories back.");
  }

  log("INFO", `Creating backup at: ${backupDir}`);
  await ensureDir(backupDir);

  // Create subdirectories in backup
  await ensureDir(join(backupDir, "service-dirs"));
  await ensureDir(join(backupDir, "compose-files"));
  await ensureDir(join(backupDir, "renames"));

  // Backup service directories
  for (const dir of plan.serviceDirs) {
    const srcPath = join(harborHome, dir);
    const destPath = join(backupDir, "service-dirs", dir);

    try {
      await Deno.stat(srcPath); // Verify it still exists
      const command = new Deno.Command("cp", {
        args: ["-r", srcPath, destPath],
      });
      await command.output();
      log("INFO", `  Backed up directory: ${dir}`);
    } catch (error) {
      const errMsg = error instanceof Error ? error.message : String(error);
      log("WARN", `  Failed to backup directory ${dir}: ${errMsg}`);
    }
  }

  // Backup items that will be renamed
  for (const rename of plan.renames) {
    const srcPath = join(harborHome, rename.from);
    const destPath = join(backupDir, "renames", basename(rename.from));

    try {
      if (rename.type === 'dir') {
        const command = new Deno.Command("cp", {
          args: ["-r", srcPath, destPath],
        });
        await command.output();
        log("INFO", `  Backed up directory for rename: ${rename.from}`);
      } else {
        await Deno.copyFile(srcPath, destPath);
        log("INFO", `  Backed up file for rename: ${rename.from}`);
      }
    } catch (error) {
      const errMsg = error instanceof Error ? error.message : String(error);
      log("WARN", `  Failed to backup ${rename.from}: ${errMsg}`);
    }
  }

  // Backup compose files
  for (const file of plan.composeFiles) {
    const srcPath = join(harborHome, file);
    const destPath = join(backupDir, "compose-files", file);

    try {
      await Deno.copyFile(srcPath, destPath);
      log("INFO", `  Backed up file: ${file}`);
    } catch (error) {
      const errMsg = error instanceof Error ? error.message : String(error);
      log("WARN", `  Failed to backup file ${file}: ${errMsg}`);
    }
  }

  // Save migration metadata
  const metadata = {
    timestamp,
    date: new Date().toISOString(),
    harborVersion: "0.4.0",
    plan,
  };

  await Deno.writeTextFile(
    join(backupDir, "migration-metadata.json"),
    JSON.stringify(metadata, null, 2)
  );

  log("SUCCESS", `Backup created successfully`);
  return backupDir;
}

async function performMigration(plan: MigrationPlan, dryRun: boolean): Promise<MigrationResult> {
  const harborHome = Deno.cwd();
  const servicesDir = join(harborHome, "services");
  const result: MigrationResult = {
    success: true,
    movedDirs: [],
    movedFiles: [],
    renamedItems: [],
    errors: [],
  };

  if (!dryRun) {
    // Ensure services directory exists
    await ensureDir(servicesDir);
    log("INFO", "Ensured services/ directory exists");
  }

  // Migrate service directories
  log("INFO", `Migrating ${plan.serviceDirs.length} service directories...`);
  for (const dir of plan.serviceDirs) {
    const srcPath = join(harborHome, dir);
    // Rename open-webui to webui during migration
    const targetDir = dir.replace(/open-webui/g, "webui");
    const destPath = join(servicesDir, targetDir);

    if (dryRun) {
      if (dir !== targetDir) {
        log("INFO", `  [DRY RUN] Would move and rename: ${dir}/ → services/${targetDir}/`);
      } else {
        log("INFO", `  [DRY RUN] Would move: ${dir}/ → services/${dir}/`);
      }
      result.movedDirs.push(dir);
      if (dir !== targetDir) {
        result.renamedItems.push({ from: dir, to: `services/${targetDir}` });
      }
    } else {
      try {
        // Check if destination already exists
        if (await exists(destPath)) {
          // Check if destination is empty or minimal (just config files from git)
          const srcSize = await getDirSize(srcPath);
          const destSize = await getDirSize(destPath);

          // If source has significant data (>1MB) and dest is minimal (<10MB), merge them
          if (srcSize > 1024 * 1024 && destSize < 10 * 1024 * 1024) {
            log("INFO", `  Destination exists but is minimal (${formatBytes(destSize)}), will merge with source (${formatBytes(srcSize)})`);
          } else if (srcSize > 1024 * 1024 && destSize > 10 * 1024 * 1024) {
            // Both have significant data - manual intervention needed
            const errMsg = `Both ${srcPath} (${formatBytes(srcSize)}) and ${destPath} (${formatBytes(destSize)}) contain significant data. Manual merge required.`;
            log("ERROR", `  ${errMsg}`);
            result.errors.push(errMsg);
            result.success = false;
            continue;
          } else {
            log("WARN", `  Destination already exists: services/${targetDir}/, skipping`);
            continue;
          }
        } else {
          // Destination doesn't exist, create it
          await ensureDir(destPath);
        }

        // Use rsync to handle root-owned files and merge safely
        const rsyncCommand = new Deno.Command("rsync", {
          args: ["-a", `${srcPath}/`, `${destPath}/`],
        });
        const rsyncResult = await rsyncCommand.output();

        if (!rsyncResult.success) {
          const stderr = new TextDecoder().decode(rsyncResult.stderr);
          throw new Error(`rsync failed: ${stderr}`);
        }

        // Remove source directory after successful rsync
        await Deno.remove(srcPath, { recursive: true });

        if (dir !== targetDir) {
          log("SUCCESS", `  Moved and renamed: ${dir}/ → services/${targetDir}/`);
          result.renamedItems.push({ from: dir, to: `services/${targetDir}` });
        } else {
          log("SUCCESS", `  Moved: ${dir}/ → services/${dir}/`);
        }
        result.movedDirs.push(dir);
      } catch (error) {
        const errMsg = `Failed to move ${dir}: ${error instanceof Error ? error.message : String(error)}`;
        log("ERROR", `  ${errMsg}`);
        result.errors.push(errMsg);
        result.success = false;
      }
    }
  }

  // Migrate compose files
  log("INFO", `Migrating ${plan.composeFiles.length} compose files...`);
  for (const file of plan.composeFiles) {
    const srcPath = join(harborHome, file);
    // Rename open-webui to webui during migration
    const targetFile = file.replace(/open-webui/g, "webui");
    const destPath = join(servicesDir, targetFile);

    if (dryRun) {
      if (file !== targetFile) {
        log("INFO", `  [DRY RUN] Would move and rename: ${file} → services/${targetFile}`);
      } else {
        log("INFO", `  [DRY RUN] Would move: ${file} → services/${file}`);
      }
      result.movedFiles.push(file);
      if (file !== targetFile) {
        result.renamedItems.push({ from: file, to: `services/${targetFile}` });
      }
    } else {
      try {
        // Check if destination already exists
        if (await exists(destPath)) {
          // For compose files, compare content to see if they're identical
          try {
            const srcContent = await Deno.readTextFile(srcPath);
            const destContent = await Deno.readTextFile(destPath);

            if (srcContent === destContent) {
              log("INFO", `  Destination exists with identical content: services/${targetFile}, removing source`);
              await Deno.remove(srcPath);
              result.movedFiles.push(file);
              continue;
            } else {
              log("INFO", `  Destination exists with different content, replacing with source: services/${targetFile}`);
              await Deno.remove(destPath);
            }
          } catch {
            // If we can't read/compare, assume they're different and replace
            await Deno.remove(destPath);
          }
        }

        // Use mv command for consistency
        const mvCommand = new Deno.Command("mv", {
          args: [srcPath, destPath],
        });
        const mvResult = await mvCommand.output();

        if (!mvResult.success) {
          const stderr = new TextDecoder().decode(mvResult.stderr);
          throw new Error(`mv failed: ${stderr}`);
        }

        if (file !== targetFile) {
          log("SUCCESS", `  Moved and renamed: ${file} → services/${targetFile}`);
          result.renamedItems.push({ from: file, to: `services/${targetFile}` });
        } else {
          log("SUCCESS", `  Moved: ${file} → services/${file}`);
        }
        result.movedFiles.push(file);
      } catch (error) {
        const errMsg = `Failed to move ${file}: ${error instanceof Error ? error.message : String(error)}`;
        log("ERROR", `  ${errMsg}`);
        result.errors.push(errMsg);
        result.success = false;
      }
    }
  }

  // Perform open-webui → webui renames
  if (plan.renames.length > 0) {
    log("INFO", `Renaming ${plan.renames.length} open-webui items to webui...`);
    for (const rename of plan.renames) {
      const srcPath = join(harborHome, rename.from);
      const destPath = join(harborHome, rename.to);

      if (dryRun) {
        log("INFO", `  [DRY RUN] Would rename: ${rename.from} → ${rename.to}`);
        result.renamedItems.push({ from: rename.from, to: rename.to });
      } else {
        try {
          // Check if destination already exists
          if (await exists(destPath)) {
            log("WARN", `  Destination already exists: ${rename.to}, skipping rename`);
            continue;
          }

          // Check if source exists
          if (!await exists(srcPath)) {
            log("WARN", `  Source not found: ${rename.from}, skipping rename`);
            continue;
          }

          // Use mv command to handle all cases consistently
          const mvCommand = new Deno.Command("mv", {
            args: [srcPath, destPath],
          });
          const mvResult = await mvCommand.output();

          if (!mvResult.success) {
            const stderr = new TextDecoder().decode(mvResult.stderr);
            throw new Error(`mv failed: ${stderr}`);
          }

          log("SUCCESS", `  Renamed: ${rename.from} → ${rename.to}`);
          result.renamedItems.push({ from: rename.from, to: rename.to });
        } catch (error) {
          const errMsg = `Failed to rename ${rename.from}: ${error instanceof Error ? error.message : String(error)}`;
          log("ERROR", `  ${errMsg}`);
          result.errors.push(errMsg);
          result.success = false;
        }
      }
    }
  }

  return result;
}

async function verifyMigration(): Promise<boolean> {
  log("INFO", "Verifying migration...");

  const harborHome = Deno.cwd();

  // Check that services directory exists
  const servicesDir = join(harborHome, "services");
  if (!await exists(servicesDir)) {
    log("ERROR", "  services/ directory does not exist!");
    return false;
  }

  // Try to run harbor ls to verify system works
  try {
    const command = new Deno.Command("bash", {
      args: [join(harborHome, "harbor.sh"), "ls"],
      stdout: "piped",
      stderr: "piped",
      env: { HARBOR_LOG_LEVEL: "error" }, // Suppress logs
    });

    const { success } = await command.output();

    if (success) {
      log("SUCCESS", "  harbor ls command works correctly");
      return true;
    } else {
      log("ERROR", "  harbor ls command failed");
      return false;
    }
  } catch (error) {
    const errMsg = error instanceof Error ? error.message : String(error);
    log("ERROR", `  Failed to verify with harbor ls: ${errMsg}`);
    return false;
  }
}

async function rollback(backupDir: string): Promise<boolean> {
  log("INFO", `Rolling back migration from backup: ${backupDir}`);

  const harborHome = Deno.cwd();

  // Verify backup directory exists
  if (!await exists(backupDir)) {
    log("ERROR", `Backup directory not found: ${backupDir}`);
    return false;
  }

  // Load migration metadata
  const metadataPath = join(backupDir, "migration-metadata.json");
  if (!await exists(metadataPath)) {
    log("ERROR", "Backup metadata not found. Cannot safely rollback.");
    return false;
  }

  const metadata = JSON.parse(await Deno.readTextFile(metadataPath));
  const plan: MigrationPlan = metadata.plan;

  log("INFO", `Restoring ${plan.serviceDirs.length} directories, ${plan.composeFiles.length} files, and ${plan.renames?.length || 0} renamed items...`);

  let success = true;

  // Restore service directories
  for (const dir of plan.serviceDirs) {
    const backupPath = join(backupDir, "service-dirs", dir);
    const destPath = join(harborHome, dir);

    try {
      if (await exists(backupPath)) {
        // Remove current version in services/ if it exists
        const servicesPath = join(harborHome, "services", dir);
        if (await exists(servicesPath)) {
          await Deno.remove(servicesPath, { recursive: true });
        }

        // Restore from backup
        const command = new Deno.Command("cp", {
          args: ["-r", backupPath, destPath],
        });
        await command.output();
        log("SUCCESS", `  Restored: ${dir}/`);
      }
    } catch (error) {
      const errMsg = error instanceof Error ? error.message : String(error);
      log("ERROR", `  Failed to restore ${dir}: ${errMsg}`);
      success = false;
    }
  }

  // Restore compose files
  for (const file of plan.composeFiles) {
    const backupPath = join(backupDir, "compose-files", file);
    const destPath = join(harborHome, file);

    try {
      if (await exists(backupPath)) {
        // Remove current version in services/ if it exists
        const servicesPath = join(harborHome, "services", file);
        if (await exists(servicesPath)) {
          await Deno.remove(servicesPath);
        }

        // Restore from backup
        await Deno.copyFile(backupPath, destPath);
        log("SUCCESS", `  Restored: ${file}`);
      }
    } catch (error) {
      const errMsg = error instanceof Error ? error.message : String(error);
      log("ERROR", `  Failed to restore ${file}: ${errMsg}`);
      success = false;
    }
  }

  // Restore renamed items
  if (plan.renames && plan.renames.length > 0) {
    for (const rename of plan.renames) {
      const backupPath = join(backupDir, "renames", basename(rename.from));
      const destPath = join(harborHome, rename.from);

      try {
        if (await exists(backupPath)) {
          // Remove the renamed version if it exists
          const renamedPath = join(harborHome, rename.to);
          if (await exists(renamedPath)) {
            if (rename.type === 'dir') {
              await Deno.remove(renamedPath, { recursive: true });
            } else {
              await Deno.remove(renamedPath);
            }
          }

          // Restore to original name
          if (rename.type === 'dir') {
            const command = new Deno.Command("cp", {
              args: ["-r", backupPath, destPath],
            });
            await command.output();
            log("SUCCESS", `  Restored renamed directory: ${rename.from}`);
          } else {
            await Deno.copyFile(backupPath, destPath);
            log("SUCCESS", `  Restored renamed file: ${rename.from}`);
          }
        }
      } catch (error) {
        const errMsg = error instanceof Error ? error.message : String(error);
        log("ERROR", `  Failed to restore renamed item ${rename.from}: ${errMsg}`);
        success = false;
      }
    }
  }

  if (success) {
    log("SUCCESS", "Rollback completed successfully");
    log("INFO", `Backup preserved at: ${backupDir}`);
  } else {
    log("ERROR", "Rollback completed with errors");
  }

  return success;
}

async function main() {
  const args = parse(Deno.args, {
    boolean: ["dry-run", "force", "help"],
    string: ["rollback"],
    alias: { h: "help" },
  });

  if (args.help) {
    console.log(`
Harbor 0.4.0 Migration Tool

Usage:
  harbor migrate [options]

Options:
  --dry-run           Preview migration without making changes
  --force             Skip confirmation prompts
  --rollback=<dir>    Rollback migration from backup directory
  -h, --help          Show this help message

Examples:
  harbor migrate --dry-run    # Preview what would be migrated
  harbor migrate              # Run migration with confirmation
  harbor migrate --force      # Run migration without confirmation
  harbor migrate --rollback=.migration-backup-1234567890
`);
    return;
  }

  // Handle rollback
  if (args.rollback) {
    const success = await rollback(args.rollback);
    Deno.exit(success ? 0 : 1);
    return;
  }

  // Normal migration flow
  console.log(`${colors.bold}${colors.cyan}
╔════════════════════════════════════════════════════════════╗
║           Harbor 0.4.0 Migration Tool                      ║
║       Restructuring services to services/ directory        ║
╚════════════════════════════════════════════════════════════╝
${colors.reset}
`);

  // Step 1: Pre-flight checks
  log("INFO", "Step 1/5: Pre-flight checks");
  const { canProceed, warnings } = await checkPreflightConditions();

  if (!canProceed) {
    Deno.exit(1);
  }

  if (warnings.length > 0) {
    log("WARN", "Warnings detected:");
    warnings.forEach(w => log("WARN", `  - ${w}`));

    if (!args.force && !args["dry-run"]) {
      console.log("\nPress Ctrl+C to cancel, or Enter to continue...");
      const buf = new Uint8Array(1);
      await Deno.stdin.read(buf);
    }
  }

  // Fix filesystem permissions before migration
  if (!args["dry-run"]) {
    log("INFO", "Running harbor fixfs to fix filesystem permissions...");
    const fixfsCommand = new Deno.Command("harbor", {
      args: ["fixfs"],
      stdout: "inherit",
      stderr: "inherit",
    });
    const fixfsResult = await fixfsCommand.output();
    if (!fixfsResult.success) {
      log("WARN", "harbor fixfs returned non-zero exit code, but continuing migration");
    }
  }

  // Step 2: Detection
  log("INFO", "Step 2/5: Detecting files to migrate");
  const plan = await detectMigration();

  if (!plan.needsMigration) {
    log("SUCCESS", "No migration needed! Your Harbor installation is already up to date.");
    log("INFO", "All service files are in the services/ directory.");
    Deno.exit(0);
  }

  console.log(`
${colors.bold}Migration Plan:${colors.reset}
  Service directories to move: ${colors.yellow}${plan.serviceDirs.length}${colors.reset}
  Compose files to move:       ${colors.yellow}${plan.composeFiles.length}${colors.reset}
  Items to rename:             ${colors.yellow}${plan.renames.length}${colors.reset}
`);

  if (plan.serviceDirs.length > 0) {
    log("INFO", "Service directories:");
    plan.serviceDirs.forEach(d => console.log(`    - ${d}/`));
  }

  if (plan.composeFiles.length > 0) {
    log("INFO", "Compose files:");
    plan.composeFiles.forEach(f => console.log(`    - ${f}`));
  }

  if (plan.renames.length > 0) {
    log("INFO", "Renames (open-webui → webui):");
    plan.renames.forEach(r => console.log(`    - ${r.from} → ${r.to}`));
  }

  // Step 3: Confirmation (unless --force or --dry-run)
  if (!args.force && !args["dry-run"]) {
    console.log(`
${colors.yellow}${colors.bold}⚠ This will modify your Harbor installation!${colors.reset}

A backup will be created before making any changes.
You can rollback the migration if needed.

Do you want to proceed? (yes/no): `);

    const confirmation = prompt("");
    if (confirmation?.toLowerCase() !== "yes") {
      log("INFO", "Migration cancelled by user.");
      Deno.exit(0);
    }
  }

  // Step 4: Backup (skip for dry-run)
  let backupDir: string | undefined;
  if (!args["dry-run"]) {
    log("INFO", "Step 3/5: Creating backup");
    backupDir = await createBackup(plan);
  } else {
    log("INFO", "Step 3/5: Skipping backup (dry-run mode)");
  }

  // Step 5: Migration
  log("INFO", args["dry-run"] ? "Step 4/5: Previewing migration" : "Step 4/5: Performing migration");
  const result = await performMigration(plan, args["dry-run"]);

  if (args["dry-run"]) {
    console.log(`
${colors.bold}Dry Run Summary:${colors.reset}
  Would move ${result.movedDirs.length} directories
  Would move ${result.movedFiles.length} files
  Would rename ${result.renamedItems.length} items

Run without --dry-run to perform actual migration.
`);
    Deno.exit(0);
  }

  if (!result.success) {
    log("ERROR", "Migration failed with errors!");
    log("INFO", `Backup preserved at: ${backupDir}`);
    log("INFO", `To rollback, run: harbor migrate --rollback=${backupDir}`);
    Deno.exit(1);
  }

  // Step 6: Verification
  log("INFO", "Step 5/5: Verifying migration");
  const verified = await verifyMigration();

  if (verified) {
    console.log(`
${colors.green}${colors.bold}✓ Migration completed successfully!${colors.reset}

Summary:
  Moved ${result.movedDirs.length} service directories
  Moved ${result.movedFiles.length} compose files
  Renamed ${result.renamedItems.length} items (open-webui → webui)
  Backup location: ${backupDir}

${colors.bold}Next Steps:${colors.reset}
  1. Test your services: ${colors.cyan}harbor up <service>${colors.reset}
  2. Verify everything works correctly
  3. Once confirmed, you can delete the backup: ${colors.cyan}rm -rf ${backupDir}${colors.reset}

${colors.bold}If you encounter issues:${colors.reset}
  Rollback: ${colors.cyan}harbor migrate --rollback=${backupDir}${colors.reset}

See docs/0.4.0-Migration-Guide.md for more information.
`);
  } else {
    log("ERROR", "Migration completed but verification failed!");
    log("INFO", `Backup preserved at: ${backupDir}`);
    log("INFO", `To rollback, run: harbor migrate --rollback=${backupDir}`);
    Deno.exit(1);
  }
}

if (import.meta.main) {
  try {
    await main();
  } catch (error) {
    const errMsg = error instanceof Error ? error.message : String(error);
    log("ERROR", `Unexpected error: ${errMsg}`);
    if (error instanceof Error && error.stack) {
      console.error(error.stack);
    }
    Deno.exit(1);
  }
}
