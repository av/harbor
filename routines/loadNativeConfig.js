// routines/loadNativeConfig.js
//
// Deno routine to safely parse a <handle>_native.yml file and print its contents
// as Bash-friendly 'local' variable assignments for use with `eval`.
// This is the primary and only approved YAML parser for the native feature.

import { parse } from "https://deno.land/std@0.224.0/yaml/parse.ts";

function sanitizeForBash(value) {
  if (typeof value !== 'string') {
    // For non-string types, especially arrays from healthchecks, JSON stringify is safe.
    return JSON.stringify(String(value)).replace(/'/g, "'\\''");
  }
  // Escape single quotes for safe inclusion in Bash's single-quoted strings.
  return value.replace(/'/g, "'\\''");
}

async function loadNativeConfig(filePath) {
  try {
    const yamlContent = await Deno.readTextFile(filePath);
    const config = parse(yamlContent);

    // Helper to safely get a nested property, returning a default if not found.
    const getProp = (obj, path, defaultValue = '') => {
      const value = path.split('.').reduce((acc, part) => (acc && acc[part] !== undefined) ? acc[part] : undefined, obj);
      return value ?? defaultValue;
    };

    // Extract all required values from the YAML contract.
    const native_executable = getProp(config, 'native_executable');
    const native_daemon_command = getProp(config, 'native_daemon_command');
    const native_port = getProp(config, 'native_port');
    const requires_gpu = getProp(config, 'requires_gpu_passthrough', 'false').toString();
    const proxy_image = getProp(config, 'proxy_image');
    const proxy_command = getProp(config, 'proxy_command');
    const healthcheck_test = getProp(config, 'proxy_healthcheck_test', []);

    // Print as a single line of Bash code for `eval`. Each variable is declared
    // `local` to prevent polluting the global scope of harbor.sh.
    // Values are sanitized to handle single quotes and other special characters.
    console.log(
      `local NATIVE_EXECUTABLE='${sanitizeForBash(native_executable)}';` +
      `local NATIVE_DAEMON_COMMAND='${sanitizeForBash(native_daemon_command)}';` +
      `local NATIVE_PORT='${sanitizeForBash(native_port)}';` +
      `local NATIVE_REQUIRES_GPU='${sanitizeForBash(requires_gpu)}';` +
      `local NATIVE_PROXY_IMAGE='${sanitizeForBash(proxy_image)}';` +
      `local NATIVE_PROXY_COMMAND='${sanitizeForBash(proxy_command)}';` +
      `local NATIVE_PROXY_HEALTHCHECK_TEST='${sanitizeForBash(healthcheck_test)}';`
    );

  } catch (error) {
    // Print error to stderr so harbor.sh can catch it and report it.
    console.error(`ERROR: Failed to parse YAML file ${filePath}: ${error.message}`);
    Deno.exit(1);
  }
}

// Main execution block
if (Deno.args.length === 0) {
  console.error("ERROR: No file path provided to loadNativeConfig.js routine.");
  Deno.exit(1);
}

const filePath = Deno.args[0];
await loadNativeConfig(filePath);
