// deno run -A ./.scripts/scaffold.ts <handle>

import { parse } from "https://deno.land/std/flags/mod.ts";
import { ensureDir } from "https://deno.land/std/fs/mod.ts";
import { join } from "https://deno.land/std/path/mod.ts";

const composeTemplate = (handle: string) => {
  const envPrefix = `HARBOR_${handle.toUpperCase()}_`;

  return `
services:
  ${handle}:
    container_name: \${HARBOR_CONTAINER_PREFIX}.${handle}
    image: \${${envPrefix}IMAGE}:\${${envPrefix}VERSION}
    env_file:
      - ./.env
      - ${handle}/override.env
    networks:
      - harbor-network
`;
};

const envTemplate = (handle: string) => `# This file can be used for additional environment variables
# specifically for the '${handle}' service.
# You can also use the "harbor env" command to set these variables.
`;

async function scaffold(handle: string) {
  try {
    // Validate handle
    if (!handle.match(/^[a-z0-9-]+$/)) {
      throw new Error(
        "Handle must contain only lowercase letters, numbers, and hyphens"
      );
    }

    // Create directory
    const dirPath = join(Deno.cwd(), handle);
    await ensureDir(dirPath);

    // Create compose file
    const composePath = join(Deno.cwd(), `compose.${handle}.yml`);
    await Deno.writeTextFile(composePath, composeTemplate(handle));

    // Create env file
    const envPath = join(dirPath, "override.env");
    await Deno.writeTextFile(envPath, envTemplate(handle));

    console.log(`Successfully created scaffold for '${handle}'`);
  } catch (error) {
    console.error("Error:", error.message);
    Deno.exit(1);
  }
}

// Parse command line arguments
const args = parse(Deno.args);
const handle = args._[0];

if (!handle) {
  console.error("Please provide a handle argument");
  Deno.exit(1);
}

await scaffold(String(handle));
