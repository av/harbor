import * as yaml from "jsr:@std/yaml";
import { deepMerge } from "jsr:@std/collections/deep-merge";

import { paths } from "./paths";
import { getArgs, log } from "./utils";
import { composeCommand, resolveComposeFiles } from "./docker";

export async function mergeComposeFiles(args) {
  const { serviceOptions, excludeServices, outputFile } = parseHarborArgs(args);
  const sourceFiles = await resolveComposeFiles(serviceOptions, excludeServices);

  // Determine output file path
  const outputPath = outputFile || paths.mergedYaml;

  // Merge all files into a single file
  // to avoid docker-compose own merge logic that is very slow for
  // larger amount of files
  await Promise.all(
    sourceFiles.map(async (file) => yaml.parse(await Deno.readTextFile(file)))
  )
    .then((contents) =>
      contents.reduce((acc, next) => deepMerge(acc, next), {})
    )
    .then((merged) =>
      Deno.writeTextFile(outputPath, yaml.stringify(merged))
    );

  // Communicate the command back to bash
  console.log(composeCommand(`-f ${paths.home}/${outputPath}`));
}

/**
 * Parse Harbor-specific arguments for compose file merging
 * Supports: -x/--exclude <services...>, --output <file>, service options
 * Format: [-x service1 service2] [--output file] [service_options...]
 */
function parseHarborArgs(args) {
  const result = {
    serviceOptions: [],
    excludeServices: [],
    outputFile: null
  };

  let i = 0;
  while (i < args.length) {
    const arg = args[i];

    if (arg === '-x' || arg === '--exclude') {
      i++; // Skip the flag
      // Collect services until next flag, '--', or end
      while (i < args.length && !args[i].startsWith('-') && args[i] !== '--') {
        const service = args[i];
        if (isValidServiceName(service)) {
          result.excludeServices.push(service);
          log.debug(`Will exclude service: ${service}`);
        } else {
          log.warn(`Invalid service name for exclusion: ${service}`);
        }
        i++;
      }
      // If we hit '--', skip it and continue with service options
      if (args[i] === '--') {
        i++;
      }
    } else if (arg === '--output') {
      if (i + 1 < args.length) {
        result.outputFile = args[i + 1];
        i += 2;
      } else {
        log.warn('--output flag requires a filename');
        i++;
      }
    } else if (arg === '--') {
      // Skip separator and treat rest as service options
      i++;
      while (i < args.length) {
        result.serviceOptions.push(args[i]);
        i++;
      }
    } else {
      // All other arguments are service options
      result.serviceOptions.push(arg);
      i++;
    }
  }

  log.debug(`Parsed args - Services: ${result.serviceOptions.length}, Exclusions: ${result.excludeServices.length}`);
  return result;
}

/**
 * Validate service name format
 */
function isValidServiceName(name) {
  return typeof name === 'string' &&
         name.length > 0 &&
         /^[a-zA-Z0-9_-]+$/.test(name);
}

if (import.meta.main === true) {
  const args = getArgs();
  mergeComposeFiles(args).catch((err) => log(err));
}