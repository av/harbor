import { red, yellow, gray } from "jsr:@std/fmt/colors";

export const BUILTIN_CAPS = ["nvidia", "mdc", "cdi"];
export const CONFIG_PREFIX = "HARBOR_";
export const LOG_LEVELS = ["debug", "info", "warn", "error"];

export function errorToString(err) {
  if (err instanceof Error) {
    return err.stack || err.message || String(err);
  }

  if (typeof err === "object") {
    return JSON.stringify(err);
  }

  return String(err);
}

function _log(...args) {
  process.stderr.write(args.join(" ") + "\n");
}

export function time() {
  const d = new Date();
  const hours = d.getHours().toString().padStart(2, "0");
  const minutes = d.getMinutes().toString().padStart(2, "0");
  const seconds = d.getSeconds().toString().padStart(2, "0");
  return `${hours}:${minutes}:${seconds}`;
}

const currentLogLevel = (
  process.env.HARBOR_LOG_LEVEL ||
  process.env.LOG_LEVEL ||
  "INFO"
).toLocaleLowerCase();

function logRouter(level, fn) {
  if (LOG_LEVELS.indexOf(level) >= LOG_LEVELS.indexOf(currentLogLevel)) {
    return (...args) => {
      fn(...args);
    };
  }

  return () => { };
}

export const log = Object.assign(_log, {
  debug: logRouter("debug", (...args) =>
    log(`${gray(time())} [${gray("DEBUG")}]`, gray(args.join(" ")))
  ),
  error: logRouter("error", (...args) =>
    log(`${gray(time())} [${red("ERROR")}]`, ...args)
  ),
  info: logRouter("info", (...args) => log(`${gray(time())} [INFO]`, ...args)),
  warn: logRouter("warn", (...args) =>
    log(`${gray(time())} [${yellow("WARN")}]`, ...args)
  ),
});

export function getArgs() {
  return process.argv.slice(2);
}

export function shiftArgs(args, n = 1) {
  return args.slice(n);
}

export function nextTick() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

export function once(fn) {
  let result;
  let called = false;

  return (...args) => {
    if (called) {
      return result;
    }

    result = fn(...args);
    called = true;
    return result;
  };
}

/**
 * Plucks an argument from the args array based on the provided aliases.
 * Modifies the args array by removing the plucked argument.
 * Aliases can be a single string or an array of strings.
 *
 * @param {string[]} args
 * @param {string|string[]} aliases
 */
export function consumeFlagArg(args, aliases) {
  if (typeof aliases === "string") {
    aliases = [aliases];
  }

  for (const alias of aliases) {
    const index = args.indexOf(alias);

    if (index !== -1) {
      args.splice(index, 1);
      return true;
    }
  }

  return false;
}

/**
 * Plucks an argument from the args array based on the provided aliases.
 * Modifies the args array by removing the plucked argument and its value.
 * Aliases can be a single string or an array of strings.
 *
 * @param {string[]} args
 * @param {string|string[]} aliases
 * @returns
 */
export function consumeArg(args, aliases) {
  if (typeof aliases === "string") {
    aliases = [aliases];
  }

  for (const alias of aliases) {
    const index = args.indexOf(alias);

    if (index !== -1 && index + 1 < args.length) {
      const value = args[index + 1];
      args.splice(index, 2);
      return value;
    }
  }

  return undefined;
}

/**
 * @param {string} input
 * @returns {string}
 */
export function decodeBashValue(input) {
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
export function encodeBashValue(value) {
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

const fileCache = new Map();

export function cachedReadFile(path: string) {
  if (!fileCache.has(path)) {
    fileCache.set(path, Deno.readTextFile(path));
  }

  return fileCache.get(path);
}