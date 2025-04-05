import { red, yellow, gray } from "jsr:@std/fmt/colors";

export const BUILTIN_CAPS = ["nvidia", "mdc", "cdi"];
export const SCRAMBLE_EXIT_CODE = 42;
export const CLI_NAME = "harbor";
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

  return () => {};
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