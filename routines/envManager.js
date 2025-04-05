import { CONFIG_PREFIX, log } from "./utils";
import { paths } from './paths';

export const TOOLS_CONFIG_KEY = 'tools';

/**
 * @param {string} input
 * @returns {string}
 */
function decodeBashValue(input) {
  if (!input) return '';

  // Trim surrounding whitespace
  input = input.trim();

  // Single-quoted: literal content, no escape sequences interpreted
  if (input.startsWith("'") && input.endsWith("'")) {
    return input.slice(1, -1);
  }

  // Double-quoted: interpret escape sequences
  if (input.startsWith('"') && input.endsWith('"')) {
    const inner = input.slice(1, -1);
    return inner.replace(/\\(["\\$`nrt])/g, (_, ch) => {
      switch (ch) {
        case 'n': return '\n';
        case 'r': return '\r';
        case 't': return '\t';
        case '"': return '"';
        case '\\': return '\\';
        case '$': return '$';
        case '`': return '`';
        default: return ch;
      }
    });
  }

  // Unquoted: interpret backslash escapes
  return input.replace(/\\(.)/g, '$1');
}

/**
 * @param {string} value
 * @returns {string}
 */
function encodeBashValue(value) {
  if (value === '') return '""'; // empty string must be quoted

  // Safe unquoted characters: alphanumerics and a few symbols
  const safeUnquoted = /^[a-zA-Z0-9._\/-]+$/;
  if (safeUnquoted.test(value)) {
    return value;
  }

  // Prefer single quotes unless the string contains single quotes
  if (!value.includes("'")) {
    return `'${value}'`;
  }

  // Fallback: use double quotes and escape necessary characters
  const escaped = value.replace(/["\\$`]/g, '\\$&')
    .replace(/\n/g, '\\n')
    .replace(/\r/g, '\\r')
    .replace(/\t/g, '\\t');

  return `"${escaped}"`;
}

/**
 * @typedef {Object} EnvKey
 * @property {string} key - The key to convert.
 * @property {string} [prefix] - Config name prefix to use.
 */

/**
 * @typedef {object} EnvProfileKey
 * @property {string} [profile] - The profile to use.
 *
 * @typedef {EnvKey & EnvProfileKey} EnvValuePointer
 */

/**
 * @typedef {object} EnvProfileValue
 * @property {string} value - The value to set.
 *
 * @typedef {EnvKey & EnvProfileKey & EnvProfileValue } EnvValueSetter
 */

/**
 * @typedef {object} EnvProfileJsonValue
 * @property {object} value - The value to set.
 *
 * @typedef {EnvKey & EnvProfileKey & EnvProfileJsonValue } EnvJsonValueSetter
 */

/**
 * Convert input config key into a Harbor profile key.
 *
 * @param {Object} config
 * @param {string} config.key - The input key to convert.
 * @param {string} [config.prefix] - Config name prefix to use.
 * @returns {Promise<string>}
 */
export async function toEnvKey({
  key,
  prefix = CONFIG_PREFIX,
}) {
  const envKey = key
    .replace(/-/g, "_")
    .replace(/\./g, "_")
    .toUpperCase();

  return prefix + envKey;
}

/**
 * Get given value from the env profile.
 *
 * @param {EnvValuePointer} config
 * @returns {Promise<string>}
 */
export async function getValue({
  profile = paths.currentProfile,
  prefix = CONFIG_PREFIX,
  key,
}) {
  const finalKey = await toEnvKey({ key, prefix });
  const contents = await Deno.readTextFile(profile);
  const line = contents
    .split("\n")
    .find((line) => line.startsWith(`${finalKey}=`));

  if (!line) {
    log.error(`Key ${finalKey} not found in ${profile}`);
    return '';
  }

  const value = line.split("=")[1];
  return decodeBashValue(value);
}

/**
 * Set given value in the env profile.
 * @param {EnvValueSetter} config
 */
export async function setValue({
  key,
  value,
  profile = paths.currentProfile,
  prefix = CONFIG_PREFIX,
}) {
  const finalKey = await toEnvKey({ key, prefix });
  const contents = await Deno.readTextFile(profile);
  const lines = contents.split("\n").map((line) => {
    const isTarget = line.startsWith(`${finalKey}=`);

    if (isTarget) {
      return `${finalKey}="${encodeBashValue(value)}"`;
    }

    return line;
  });

  await Deno.writeTextFile(profile, lines.join("\n"));
}

/**
 * @param {EnvValuePointer} config
 * @returns {Promise<object>}
 */
export async function getJsonValue(config) {
  const value = await getValue(config);

  if (value === '') {
    return {};
  }

  try {
    return JSON.parse(value);
  } catch (e) {
    log.error(`Failed to parse JSON value: ${e}`);
    process.exit(1);
  }
}

/**
 * @param {EnvJsonValueSetter} config
 * @returns {Promise<void>}
 */
export async function setJsonValue(config) {
  const json = JSON.stringify(config.value);
  await setValue({ ...config, value: json });
}