import fs from 'node:fs';
import process from 'node:process';
import { CONFIG_PREFIX, decodeBashValue, getArgs, log } from './utils';
import { paths } from './paths';

interface ParsedLine {
  displayKey: string;
  value: string;
}

function parseEnvLines(contents: string, prefix: string): ParsedLine[] {
  const results: ParsedLine[] = [];

  for (const line of contents.split('\n')) {
    if (!line.startsWith(prefix)) continue;

    const eqIdx = line.indexOf('=');
    if (eqIdx === -1) continue;

    const key = line.slice(0, eqIdx);
    const rawValue = line.slice(eqIdx + 1);
    const stripped = key.slice(prefix.length);
    const displayKey = prefix
      ? stripped.toLowerCase().replace(/_/, '.')
      : stripped;

    results.push({ displayKey, value: decodeBashValue(rawValue) });
  }

  return results;
}

function normalize(s: string): string {
  return s.replace(/[.\-]/g, '_');
}

function printEntries(entries: ParsedLine[]) {
  for (const { displayKey, value } of entries) {
    console.log(`${displayKey.padEnd(30)} ${value}`);
  }
}

function parseFlags(args: string[]): { envFile: string; prefix: string; rest: string[] } {
  let envFile = paths.currentProfile;
  let prefix = CONFIG_PREFIX;

  while (args.length > 0 && args[0].startsWith('--')) {
    if (args[0] === '--env-file' && args.length > 1) {
      envFile = args[1];
      args = args.slice(2);
    } else if (args[0] === '--prefix' && args.length > 1) {
      prefix = args[1];
      args = args.slice(2);
    } else {
      args = args.slice(1);
    }
  }

  return { envFile, prefix, rest: args };
}

async function readEnvFile(envFile: string): Promise<string> {
  try {
    return await fs.promises.readFile(envFile, 'utf-8');
  } catch {
    log.error(`Cannot read env file: ${envFile}`);
    process.exit(1);
  }
}

async function main(args: string[]) {
  const command = args[0];
  const flagArgs = args.slice(1);
  const { envFile, prefix, rest } = parseFlags(flagArgs);
  const contents = await readEnvFile(envFile);
  const entries = parseEnvLines(contents, prefix);

  switch (command) {
    case 'list': {
      printEntries(entries);
      break;
    }
    case 'search': {
      const query = rest[0];
      if (!query) {
        console.log('Usage: harbor config search <query>');
        process.exit(1);
      }

      const queryLc = query.toLowerCase();
      const normalizedQuery = normalize(queryLc);

      const matches = entries.filter(({ displayKey, value }) => {
        const hyphenKey = displayKey.replace(/\./g, '-');
        const normalizedKey = normalize(displayKey);
        const searchBlob = `${displayKey} ${value.toLowerCase()} ${hyphenKey} ${normalizedKey}`;
        return searchBlob.includes(queryLc) || searchBlob.includes(normalizedQuery);
      });

      if (matches.length === 0) {
        console.log(`No results found for: ${query}`);
        process.exit(0);
      }

      printEntries(matches);
      break;
    }
    default:
      log.error(`Unknown command: ${command}`);
      process.exit(1);
  }
}

if (import.meta.main === true) {
  main(getArgs()).catch((err) => {
    log.error(err);
    process.exit(1);
  });
}
