import { red, yellow, gray } from "jsr:@std/fmt/colors";

export const builtInCapabilities = [
  'nvidia',
  'mdc',
  'cdi',
]

export function errorToString(err) {
  if (err instanceof Error) {
    return err.stack || err.message || String(err)
  }

  if (typeof err === 'object') {
    return JSON.stringify(err)
  }

  return String(err)
}

function _log(...args) {
  process.stderr.write(args.join(' ') + '\n')
}

export function time() {
  const d = new Date()
  const hours = d.getHours().toString().padStart(2, '0')
  const minutes = d.getMinutes().toString().padStart(2, '0')
  const seconds = d.getSeconds().toString().padStart(2, '0')
  return `${hours}:${minutes}:${seconds}`
}

export const log = Object.assign(_log, {
  debug: (...args) => log(`${gray(time())} [${gray('DEBUG')}]`, gray(args.join(' '))),
  error: (...args) => log(`${gray(time())} [${red('ERROR')}]`, ...args),
  info: (...args) => log(`${gray(time())} [INFO]`, ...args),
  warn: (...args) => log(`${gray(time())} [${yellow('WARN')}]`, ...args),
})

export function getArgs() {
  return process.argv.slice(2)
}
