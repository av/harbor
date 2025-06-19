// routines/loadNativeConfig.js
//
// [v24.0] Deno routine to safely parse Harbor v22.0+ Unified Native Contract files.
// Parses <handle>_native.yml files that serve as both Docker Compose override files
// and native process metadata contracts. Outputs Bash-friendly 'local' variable
// assignments for use with `eval`.
//
// New YAML Structure (v22.0+):
// services:
//   <handle>:
//     # Proxy container definition (used by Docker Compose)
//     image: alpine/socat:latest
//     command: tcp-listen:PORT,fork,reuseaddr tcp-connect:host.docker.internal:PORT
//     healthcheck: ...
//     networks: ...
//
//     # Native process metadata (used by Harbor, ignored by Docker Compose)
//     x-harbor-native:
//       executable: "command"
//       daemon_command: "command serve"
//       port: 11434
//       requires_gpu_passthrough: true
//       env_vars: ["VAR1", "VAR2"]
//       env_overrides: {KEY: "value"}
//
// This is the primary and only approved YAML parser for the native feature.

import { parse } from "https://deno.land/std@0.224.0/yaml/parse.ts";

/**
 * Sanitizes a string value for safe inclusion in a Bash single-quoted string.
 * Escapes single quotes by replacing ' with ''\''.
 * @param {string | unknown} value The value to sanitize.
 * @returns {string} The sanitized string.
 */
function sanitizeForBash(value) {
  if (value === null || typeof value === 'undefined') return '';
  return String(value).replace(/'/g, "'\\''");
}

/**
 * Sanitizes an array of strings for safe inclusion in a Bash array expansion.
 * Each element is formatted as a single-quoted, space-separated string.
 * Example: ['a', 'b c'] becomes "'a' 'b c'"
 * @param {Array<unknown>} arr The array to sanitize.
 * @returns {string} A space-separated string of single-quoted, sanitized elements.
 */
function sanitizeArrayForBash(arr) {
  if (!Array.isArray(arr)) return '';
  return arr.map(item => `'${sanitizeForBash(item)}'`).join(' ');
}

/**
 * Sanitizes a JavaScript object for safe inclusion in a Bash array of key='value' pairs.
 * Example: { key1: 'val1', key2: 'val2' } becomes "key1='val1' key2='val2'"
 * @param {Object} obj The object to sanitize.
 * @returns {string} A space-separated string of key='value' pairs.
 */
function sanitizeDictForBash(obj) {
  if (typeof obj !== 'object' || obj === null || Array.isArray(obj)) return '';
  return Object.entries(obj)
    .map(([key, value]) => `'${sanitizeForBash(key)}=${sanitizeForBash(value)}'`)
    .join(' ');
}

async function loadNativeConfig(filePath, serviceHandle) {
  try {
    const yamlContent = await Deno.readTextFile(filePath);
    const config = parse(yamlContent);

    // Safely access the service's configuration block.
    const serviceConfig = config?.services?.[serviceHandle];
    if (!serviceConfig) {
      console.error(`ERROR: Service '${serviceHandle}' not found in ${filePath}`);
      Deno.exit(1);
    }

    // Safely access the Harbor-specific native metadata block.
    const nativeConfig = serviceConfig['x-harbor-native'];
    if (!nativeConfig) {
      console.error(`ERROR: Missing 'x-harbor-native' block in ${filePath} for service '${serviceHandle}'.`);
      Deno.exit(1);
    }

    // Helper for safe property access.
    const getProp = (obj, key, defaultValue = '') => obj?.[key] ?? defaultValue;

    // --- Extract all values from the correct locations in the YAML contract ---
    // Extract metadata for the native process itself from the 'x-harbor-native' block.
    const native_executable = getProp(nativeConfig, 'executable');
    const native_daemon_command = getProp(nativeConfig, 'daemon_command');
    const native_port = getProp(nativeConfig, 'port');
    const requires_gpu = getProp(nativeConfig, 'requires_gpu_passthrough', false).toString();
    const native_env_vars = getProp(nativeConfig, 'env_vars', []);
    const env_overrides = getProp(nativeConfig, 'env_overrides', {});

    // Extract data for the proxy container from the main service definition.
    const proxy_image = getProp(serviceConfig, 'image');
    const proxy_command = getProp(serviceConfig, 'command');

    // Extract healthcheck test command from the service's healthcheck block
    const healthcheck_block = getProp(serviceConfig, 'healthcheck', {});
    const proxy_healthcheck_test = getProp(healthcheck_block, 'test', []);

    // Extract networks from the service definition
    const proxy_networks = getProp(serviceConfig, 'networks', []);

    // Extract depends_on if present (though less common in the new structure)
    const native_depends_on = getProp(serviceConfig, 'depends_on', []);
    // Handle both array format and object format for depends_on
    const native_depends_on_array = Array.isArray(native_depends_on)
      ? native_depends_on
      : Object.keys(native_depends_on || {});

    // --- Sanitize and format for Bash output ---
    // Print as a single line of Bash code for `eval`. Each variable is declared
    // `local` to prevent polluting the global scope of harbor.sh.
    // Values are sanitized to handle single quotes and other special characters.
    const output = [
      `local NATIVE_EXECUTABLE='${sanitizeForBash(native_executable)}'`,
      `local NATIVE_DAEMON_COMMAND='${sanitizeForBash(native_daemon_command)}'`,
      `local NATIVE_PORT='${sanitizeForBash(native_port)}'`,
      `local NATIVE_REQUIRES_GPU='${sanitizeForBash(requires_gpu)}'`,
      `local NATIVE_PROXY_IMAGE='${sanitizeForBash(proxy_image)}'`,
      `local NATIVE_PROXY_COMMAND='${sanitizeForBash(proxy_command)}'`,
      `local -a NATIVE_PROXY_HEALTHCHECK_TEST=(${sanitizeArrayForBash(proxy_healthcheck_test)})`,
      `local -a NATIVE_ENV_VARS_LIST=(${sanitizeArrayForBash(native_env_vars)})`,
      `local -a NATIVE_DEPENDS_ON_CONTAINERS=(${sanitizeArrayForBash(native_depends_on_array)})`,
      `local -a NATIVE_ENV_OVERRIDES_ARRAY=(${sanitizeDictForBash(env_overrides)})`,
      `local -a NATIVE_PROXY_NETWORKS=(${sanitizeArrayForBash(proxy_networks)})`
    ];

    console.log(output.join(';'));

  } catch (error) {
    console.error(`ERROR: Failed to parse native contract ${filePath}: ${error.message}`);
    Deno.exit(1);
  }
}

// --- Main execution block ---
if (Deno.args.length < 2) {
  console.error("Usage: loadNativeConfig.js <file_path> <service_handle>");
  Deno.exit(1);
}
await loadNativeConfig(Deno.args[0], Deno.args[1]);