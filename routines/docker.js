import { listComposeFiles } from './paths';
import { BUILTIN_CAPS, log } from "./utils";

export function isCapability(capability, defaultCapabilities = BUILTIN_CAPS) {
  return defaultCapabilities.includes(capability);
}

export function isCapabilityFile(filename, defaultCapabilities = BUILTIN_CAPS) {
  return defaultCapabilities.some(cap => filename.includes(`.${cap}.`));
}

export async function resolveComposeFiles(args) {
  const options = [...args].filter((s) => !!s);
  const composeFiles = ['compose.yml'];

  // Find and sort compose files
  const allFiles = await listComposeFiles();

  for (const file of allFiles) {
    const filename = file.split("/").pop();
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
    }
  }

  log.debug("Matched compose files:", composeFiles.length);

  return composeFiles
}

export function composeCommand(args) {
  return `docker compose ${args}`;
}