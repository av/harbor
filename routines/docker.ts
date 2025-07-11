import { listComposeFiles } from './paths';
import { BUILTIN_CAPS, consumeArg, consumeFlagArg, log } from "./utils";
import { cachedConfig, defaultCapabilities, defaultServices } from './envManager';

export function isCapability(capability, defaultCapabilities = BUILTIN_CAPS) {
  return defaultCapabilities.includes(capability);
}

export function isCapabilityFile(filename, defaultCapabilities = BUILTIN_CAPS) {
  return defaultCapabilities.some(cap => filename.includes(`.${cap}.`));
}

export async function resolveComposeFiles(args) {
  const includeDefaults = !consumeFlagArg(args, ['--no-defaults']);
  const dir = consumeArg(args, ['--dir']);
  const options = [
    ...(
      await Promise.all([
        defaultCapabilities.unwrap(),
        includeDefaults ? defaultServices.unwrap() : [],
      ])
        .then((r => r.flat()))
    ),
    ...args
  ].filter((s) => !!s);
  const allFiles = await listComposeFiles(dir);
  const outFiles = ['compose.yml'];

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
        outFiles.push(file);
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
      outFiles.push(file);
    }
  }

  log.debug("Matched compose files:", outFiles.length);

  return outFiles
}

export const whichCompose = cachedConfig({
  key: 'compose.command'
})

export async function composeCommand(args) {
  return `${await whichCompose()} ${args}`;
}