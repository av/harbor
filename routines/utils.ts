/// <reference lib="deno.ns" />

import process from "node:process";

export const BUILTIN_CAPS = ["nvidia", "mdc", "cdi", "rocm", "build"];
export const CONFIG_PREFIX = "HARBOR_";
export const LOG_LEVELS = ["debug", "info", "warn", "error"];

type LogLevel = typeof LOG_LEVELS[number];
type LogFn = (...args: unknown[]) => void;
type AliasArg = string | string[];

type Logger = LogFn & {
  debug: LogFn;
  error: LogFn;
  info: LogFn;
  warn: LogFn;
};

function color(open: number, close: number, text: string): string {
  if (
    process.env.NO_COLOR || process.env.DENO_NO_COLOR ||
    process.env.TERM === "dumb"
  ) {
    return text;
  }

  return `\x1b[${open}m${text}\x1b[${close}m`;
}

function gray(text: string): string {
  return color(90, 39, text);
}

function red(text: string): string {
  return color(31, 39, text);
}

function yellow(text: string): string {
  return color(33, 39, text);
}

export function errorToString(err: unknown): string {
  if (err instanceof Error) {
    return err.stack || err.message || String(err);
  }

  if (err !== null && typeof err === "object") {
    return JSON.stringify(err);
  }

  return String(err);
}

function _log(...args: unknown[]): void {
  process.stderr.write(args.join(" ") + "\n");
}

export function time(): string {
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

function logRouter(level: LogLevel, fn: LogFn): LogFn {
  if (LOG_LEVELS.indexOf(level) >= LOG_LEVELS.indexOf(currentLogLevel)) {
    return (...args: unknown[]): void => {
      fn(...args);
    };
  }

  return () => {};
}

export const log: Logger = Object.assign(_log, {
  debug: logRouter(
    "debug",
    (...args: unknown[]) =>
      log(`${gray(time())} [${gray("DEBUG")}]`, gray(args.join(" "))),
  ),
  error: logRouter(
    "error",
    (...args: unknown[]) => log(`${gray(time())} [${red("ERROR")}]`, ...args),
  ),
  info: logRouter(
    "info",
    (...args: unknown[]) => log(`${gray(time())} [INFO]`, ...args),
  ),
  warn: logRouter(
    "warn",
    (...args: unknown[]) => log(`${gray(time())} [${yellow("WARN")}]`, ...args),
  ),
});

export function getArgs(): string[] {
  return process.argv.slice(2);
}

export function shiftArgs<T>(args: T[], n = 1): T[] {
  return args.slice(n);
}

export function nextTick(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

export function once<TArgs extends unknown[], TResult>(
  fn: (...args: TArgs) => TResult,
): (...args: TArgs) => TResult {
  let result: TResult;
  let called = false;

  return (...args: TArgs): TResult => {
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
export function consumeFlagArg(args: string[], aliases: AliasArg): boolean {
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
export function consumeArg(
  args: string[],
  aliases: AliasArg,
): string | undefined {
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
export function decodeBashValue(input: string): string {
  if (!input) return "";

  // Trim surrounding whitespace
  input = input.trim();

  // Single-quoted: literal content, no escape sequences interpreted
  if (input.startsWith("'") && input.endsWith("'")) {
    return input.slice(1, -1);
  }

  // Double-quoted: interpret escape sequences
  if (input.startsWith('"') && input.endsWith('"')) {
    const inner = input.slice(1, -1);
    return inner.replace(/\\(["\\$`nrt])/g, (_: string, ch: string): string => {
      switch (ch) {
        case "n":
          return "\n";
        case "r":
          return "\r";
        case "t":
          return "\t";
        case '"':
          return '"';
        case "\\":
          return "\\";
        case "$":
          return "$";
        case "`":
          return "`";
        default:
          return ch;
      }
    });
  }

  // Unquoted: interpret backslash escapes
  return input.replace(/\\(.)/g, "$1");
}

/**
 * @param {string} value
 * @returns {string}
 */
export function encodeBashValue(value: string): string {
  if (value === "") return '""'; // empty string must be quoted

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
  const escaped = value.replace(/["\\$`]/g, "\\$&")
    .replace(/\n/g, "\\n")
    .replace(/\r/g, "\\r")
    .replace(/\t/g, "\\t");

  return `"${escaped}"`;
}

const fileCache = new Map<string, Promise<string>>();

export function cachedReadFile(path: string): Promise<string> {
  if (!fileCache.has(path)) {
    fileCache.set(path, Deno.readTextFile(path));
  }

  return fileCache.get(path)!;
}
