import { listComposeFiles } from './paths';
import { BUILTIN_CAPS, log } from "./utils";

export function isCapability(capability, defaultCapabilities = BUILTIN_CAPS) {
  return defaultCapabilities.includes(capability);
}

export function isCapabilityFile(filename, defaultCapabilities = BUILTIN_CAPS) {
  return defaultCapabilities.some(cap => filename.includes(`.${cap}.`));
}

export async function resolveComposeFiles(args, excludeServices = []) {
  const options = [...args].filter((s) => !!s);
  const composeFiles = ['compose.yml'];

  log.debug(`Resolving compose files for options: [${options.join(', ')}], excluding: [${excludeServices.join(', ')}]`);

  // Find and sort compose files
  const allFiles = await listComposeFiles();

  for (const file of allFiles) {
    const filename = file.split("/").pop();

    // EXCLUSION LOGIC: Skip defining files for excluded services
    // This matches the Bash behavior: exclude `compose.<service>.yml` but preserve cross-service files
    const isDefiningFile = excludeServices.some(service =>
      filename === `compose.${service}.yml`
    );

    if (isDefiningFile) {
      log.debug(`Excluding defining file for native service: ${filename}`);
      continue;
    }

    let match = false;

    // Handle cross-service files
    if (filename.includes(".x.")) {
      const cross = filename.replace("compose.x.", "").replace(".yml", "");
      const filenameParts = cross.split(".");
      let allMatched = true;

      for (const part of filenameParts) {
        if (isCapability(part)) {
          // Capabilities must match exactly
          if (!options.includes(part)) {
            allMatched = false;
            break;
          }
        } else {
          // Services can match wildcards
          if (!options.includes(part) && !options.includes("*")) {
            allMatched = false;
            break;
          }
        }
      }

      if (allMatched) {
        composeFiles.push(file);
      }
      continue;
    }

    // Check if file matches any options
    for (const option of options) {
      if (option === "*") {
        if (!isCapabilityFile(filename)) {
          match = true;
          break;
        }
      }

      if (filename.includes(`.${option}.`)) {
        match = true;
        break;
      }
    }

    if (match) {
      composeFiles.push(file);
      log.debug(`Including matched file: ${filename}`);
    }
  }

  // ADD NATIVE PROXY FILES for excluded services
  // This replaces the excluded defining files with their native proxy contracts
  for (const service of excludeServices) {
    const nativeProxyFile = `${service}/${service}_native.yml`;
    try {
      const stat = await Deno.stat(nativeProxyFile);
      if (stat.isFile) {
        composeFiles.push(nativeProxyFile);
        log.debug(`Including native proxy file: ${nativeProxyFile}`);
      }
    } catch (error) {
      // File doesn't exist - this is expected for services without native support
      log.debug(`No native proxy file found for ${service}: ${nativeProxyFile}`);
    }
  }

  log.debug("Matched compose files:", composeFiles.length);
  log.debug("Final file list:", composeFiles);

  return composeFiles
}

export function composeCommand(args) {
  return `docker compose ${args}`;
}