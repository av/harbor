// routines/loadNativeConfig.js
//
// Deno routine to safely parse a <handle>_native.yml file and print its contents
// as Bash-friendly 'local' variable assignments for use with `eval`.
// This is the primary and only approved YAML parser for the native feature.

import { parse } from "https://deno.land/std@0.224.0/yaml/parse.ts";

/**
 * Sanitizes a string value for safe inclusion in a Bash single-quoted string.
 * Escapes single quotes by replacing ' with ''\''.
 * @param {string | unknown} value The value to sanitize.
 * @returns {string} The sanitized string.
 */
function sanitizeForBash(value) {
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
    .map(([key, value]) => `'${sanitizeForBash(key)}=${sanitizeForBash(value)}'`) // Each pair is a single element
    .join(' ');
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

    // --- Extract all values from the YAML contract ---
    const native_executable = getProp(config, 'native_executable');
    const native_daemon_command = getProp(config, 'native_daemon_command');
    const native_port = getProp(config, 'native_port');
    const requires_gpu = getProp(config, 'requires_gpu_passthrough', 'false').toString();
    const proxy_image = getProp(config, 'proxy_image');
    const proxy_command = getProp(config, 'proxy_command');

    // --- Extract structured data (arrays and objects) ---
    const proxy_healthcheck_test = getProp(config, 'proxy_healthcheck_test', []);
    const native_env_vars = getProp(config, 'native_env_vars', []);
    const native_depends_on = getProp(config, 'native_depends_on_containers', []);
    const env_overrides = getProp(config, 'env_overrides', {});

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
      `local -a NATIVE_DEPENDS_ON_CONTAINERS=(${sanitizeArrayForBash(native_depends_on)})`,
      `local -a NATIVE_ENV_OVERRIDES_ARRAY=(${sanitizeDictForBash(env_overrides)})`,
    ];

    console.log(output.join(';'));

  } catch (error) {
    console.error(`ERROR: Failed to parse YAML file ${filePath}: ${error.message}`);
    Deno.exit(1);
  }
}

// --- Main execution block ---
if (Deno.args.length === 0) {
  console.error("ERROR: No file path provided to loadNativeConfig.js routine.");
  Deno.exit(1);
}

const filePath = Deno.args[0];
await loadNativeConfig(filePath);