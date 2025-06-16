// routines/loadNativeConfig.js
//
// Deno routine to safely parse a harbor-native.yml file and print its contents
// as Bash-friendly KEY="VALUE" pairs.
//
// Usage: deno run -A <path_to_this_script> <path_to_harbor_native_yml>
//
// This script is executed by harbor.sh's `_harbor_load_native_config` function.

import { parse } from "https://deno.land/std@0.224.0/yaml/parse.ts";

async function loadNativeConfig(filePath) {
  try {
    const yamlContent = await Deno.readTextFile(filePath);
    const config = parse(yamlContent);

    // Helper to safely get a nested property, returning undefined if not found.
    const getProp = (obj, path) => {
      return path.split('.').reduce((acc, part) => (acc && acc[part] !== undefined) ? acc[part] : undefined, obj);
    };

    // Extract values, handling potential nesting and absence.
    const native_command = getProp(config, 'native_command') || '';
    const native_port = getProp(config, 'native_port') || '';
    const health_method = getProp(config, 'health.method') || '';
    const health_url = getProp(config, 'health.url') || '';
    const proxy_image = getProp(config, 'proxy_image') || '';
    const proxy_command = getProp(config, 'proxy_command') || '';
    const proxy_healthcheck_test = getProp(config, 'proxy_healthcheck_test') || '';

    // Handle networks array, joining with space for Bash.
    const proxy_networks_array = getProp(config, 'proxy_networks') || [];
    const proxy_networks = Array.isArray(proxy_networks_array) ? proxy_networks_array.join(' ') : '';

    // Print as Bash-friendly KEY="VALUE" pairs.
    console.log(`NATIVE_CFG_COMMAND="${native_command}"`);
    console.log(`NATIVE_CFG_PORT="${native_port}"`);
    console.log(`NATIVE_CFG_HEALTH_METHOD="${health_method}"`);
    console.log(`NATIVE_CFG_HEALTH_URL="${health_url}"`);
    console.log(`NATIVE_CFG_PROXY_IMAGE="${proxy_image}"`);
    console.log(`NATIVE_CFG_PROXY_COMMAND="${proxy_command}"`);
    console.log(`NATIVE_CFG_PROXY_HEALTHCHECK_TEST="${proxy_healthcheck_test}"`);
    console.log(`NATIVE_CFG_PROXY_NETWORKS="${proxy_networks}"`);

  } catch (error) {
    // Print error to stderr so harbor.sh can catch it.
    console.error(`ERROR: Failed to parse YAML file ${filePath}: ${error.message}`);
    Deno.exit(1); // Exit with error code.
  }
}

// Get the file path argument.
const filePath = Deno.args[0];
if (!filePath) {
  console.error("ERROR: No file path provided to loadNativeConfig.js routine.");
  Deno.exit(1);
}

await loadNativeConfig(filePath);
