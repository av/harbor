import * as yaml from "jsr:@std/yaml";
import { deepMerge } from "jsr:@std/collections/deep-merge";
import * as path from "node:path";

import { paths } from "./paths";
import { BUILTIN_CAPS, consumeFlagArg, errorToString, getArgs, log } from "./utils";
import { composeCommand, resolveComposeFiles, resolveComposeModules, isCapability } from "./docker";
import { getValue, getJsonValue, defaultServices, defaultCapabilities } from "./envManager";
import type {
  ComposeObject,
  ComposeContext,
  ComposeModuleApply,
  ComposeModuleError,
  ComposeModuleLoadError,
  ComposeModuleExecutionError
} from "./composeTypes";
import {
  ComposeModuleError as ComposeModuleErrorClass,
  ComposeModuleLoadError as ComposeModuleLoadErrorClass,
  ComposeModuleExecutionError as ComposeModuleExecutionErrorClass
} from "./composeTypes";

/**
 * Extract service name from a compose module filename.
 * Returns null for base modules or cross-files.
 */
function extractServiceFromModule(filename: string): string | null {
  const match = filename.match(/^compose\.([^.]+)\.ts$/);
  return match ? match[1] : null;
}

/**
 * Build the compose context for TypeScript modules.
 */
function buildComposeContext(
  compose: ComposeObject,
  args: string[],
  sourceFiles: string[],
  tsModules: string[],
  dir: string,
  mergeEnabled: boolean,
  modulePath: string,
  services: string[],
  capabilities: string[]
): ComposeContext {
  const service = extractServiceFromModule(modulePath.split('/').pop() || '');

  return {
    compose,
    service,
    services,
    capabilities,
    args: [...args],
    dir: path.resolve(dir || paths.home),
    mergeEnabled,
    env: {
      getValue: async (key: string) => {
        const result = await getValue({ key });
        return result || '';
      },
      getJsonValue: async (key: string) => {
        try {
          const result = await getJsonValue({ key });
          return result || {};
        } catch {
          return {};
        }
      },
    },
    files: {
      yaml: sourceFiles,
      typescript: tsModules,
    },
  };
}

/**
 * Apply TypeScript compose modules to the merged compose object.
 */
async function applyComposeModules(
  compose: ComposeObject,
  modules: string[],
  args: string[],
  sourceFiles: string[],
  dir: string,
  mergeEnabled: boolean,
  services: string[],
  capabilities: string[]
): Promise<ComposeObject> {
  let result = compose;

  for (const modulePath of modules) {
    try {
      const fullPath = `${dir || paths.home}/${modulePath}`;
      log.debug(`Loading TS compose: ${modulePath}`);

      const module = await import(fullPath);

      if (typeof module.default !== 'function') {
        throw new ComposeModuleErrorClass(
          `Module must export a default apply() function`,
          modulePath
        );
      }

      const context = buildComposeContext(
        result,
        args,
        sourceFiles,
        modules,
        dir || paths.home,
        mergeEnabled,
        modulePath,
        services,
        capabilities
      );

      log.debug(`Applying TS compose: ${modulePath}`);
      const newResult = await module.default(context);

      if (!newResult || typeof newResult !== 'object') {
        throw new ComposeModuleErrorClass(
          `Module must return a compose object`,
          modulePath
        );
      }

      result = newResult;

    } catch (err) {
      if (err instanceof ComposeModuleErrorClass) {
        throw err;
      }

      if (err.message?.includes('Cannot find module') || err.message?.includes('Module not found')) {
        throw new ComposeModuleLoadErrorClass(modulePath, err);
      }

      throw new ComposeModuleExecutionErrorClass(modulePath, err);
    }
  }

  return result;
}

export async function mergeComposeFiles(args) {
  let shouldMerge = !consumeFlagArg(args, ["--no-merge"]);
  const dir = args.find(arg => arg.startsWith('--dir='))?.split('=')[1];
  const sourceFiles = await resolveComposeFiles(args);
  let targetFiles = []

  // Extract services and capabilities from args (after flags are consumed)
  // Args at this point are the remaining service/capability names
  const allOptions = args.filter(arg => !arg.startsWith('-'));
  const defServices = await defaultServices.unwrap() || [];
  const defCaps = await defaultCapabilities.unwrap() || [];

  // Combine explicit args with defaults
  const allServicesAndCaps = [...new Set([...defServices, ...defCaps, ...allOptions])];

  // Separate services from capabilities
  const capabilities = allServicesAndCaps.filter(s => isCapability(s));
  const services = allServicesAndCaps.filter(s => !isCapability(s));

  if (shouldMerge) {
    // Merge all files into a single file
    // to avoid docker-compose own merge logic that is very slow for
    // larger amount of files
    const contents = await Promise.all(
      sourceFiles.map(async (file) => yaml.parse(await Deno.readTextFile(file)))
    )
    let merged: ComposeObject = contents.reduce((acc, next) => deepMerge(acc, next), {});

    // Apply TypeScript compose modules
    const tsModules = await resolveComposeModules([...args]);
    if (tsModules.length > 0) {
      log.debug(`Applying ${tsModules.length} TypeScript compose module(s)`);
      merged = await applyComposeModules(merged, tsModules, args, sourceFiles, dir, shouldMerge, services, capabilities);
    }

    await Deno.writeTextFile(`${paths.home}/${paths.mergedYaml}`, yaml.stringify(merged))
    targetFiles.push(`${paths.home}/${paths.mergedYaml}`);
  } else {
    // Keep files as they are
    // Note: TypeScript modules are skipped when --no-merge is used
    const tsModules = await resolveComposeModules([...args]);
    if (tsModules.length > 0) {
      log.warn("TypeScript compose modules are ignored with --no-merge flag");
    }
    targetFiles = sourceFiles.map((file) => `${paths.home}/${file}`);
  }

  console.log(await composeCommand(
    targetFiles.map((file) => `-f ${file}`).join(' '),
  ));
}

if (import.meta.main === true) {
  const args = getArgs();
  mergeComposeFiles(args).catch((err) => {
    if (err instanceof ComposeModuleErrorClass) {
      log.error(`TypeScript compose error in ${err.modulePath}:`);
      log.error(err.message);
      if (err.cause) {
        log.debug(err.cause.stack);
      }
      Deno.exit(1);
    }
    log.error(errorToString(err));
    Deno.exit(1);
  });
}
