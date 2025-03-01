import { readFileSync, writeFileSync } from 'node:fs';
import { getArgs, log } from './utils';

function parseArgs(args) {
  const options = {
    silent: false,
    envFile: '.env',
    prefix: 'HARBOR_',
  };

  while (args.length > 0 && args[0].startsWith('--')) {
    switch (args[0]) {
      case '--silent':
        options.silent = true;
        args.shift();
        break;
      case '--env-file':
        options.envFile = args[1];
        args.shift();
        args.shift();
        break;
      case '--prefix':
        options.prefix = args[1];
        args.shift();
        args.shift();
        break;
      default:
        if (!options.silent) {
          log.warn(`Unknown option: ${args[0]}`);
        }
        return null;
    }
  }

  return {
    options,
    command: args[0],
    args: args.slice(1),
  };
}

function readEnvFile(filePath) {
  try {
    const content = readFileSync(filePath, 'utf8');
    const envVars = {};

    content.split('\n').forEach(line => {
      line = line.trim();
      if (line && !line.startsWith('#')) {
        const [key, ...valueParts] = line.split('=');
        const value = valueParts.join('=')
          .replace(/^"(.*)"$/, '$1') // Remove surrounding quotes
          .replace(/^'(.*)'$/, '$1');
        envVars[key.trim()] = value.trim();
      }
    });

    return envVars;
  } catch (err) {
    throw new Error(`Failed to read env file: ${err.message}`);
  }
}

function writeEnvFile(filePath, envVars) {
  try {
    const content = Object.entries(envVars)
      .map(([key, value]) => `${key}="${value}"`)
      .join('\n');
    writeFileSync(filePath, content + '\n');
  } catch (err) {
    throw new Error(`Failed to write env file: ${err.message}`);
  }
}

function getValue(envVars, prefix, key) {
  const upperKey = key.toUpperCase().replace(/\./g, '_');
  const fullKey = prefix + upperKey;
  return envVars[fullKey];
}

function setValue(envVars, prefix, key, value) {
  const upperKey = key.toUpperCase().replace(/\./g, '_');
  const fullKey = prefix + upperKey;
  envVars[fullKey] = value;
  return envVars;
}

function listVars(envVars, prefix) {
  return Object.entries(envVars)
    .filter(([key]) => key.startsWith(prefix))
    .map(([key, value]) => ({
      key: key.replace(prefix, ''),
      value,
    }));
}

export async function envManager(args) {
  const parsed = parseArgs(args);
  if (!parsed) return 1;

  const { options, command, args: remainingArgs } = parsed;
  const envVars = readEnvFile(options.envFile);

  try {
    switch (command) {
      case 'get': {
        const value = getValue(envVars, options.prefix, remainingArgs[0]);
        if (value !== undefined) {
          return value;
        }
        break;
      }

      case 'set': {
        if (remainingArgs.length < 2) {
          if (!options.silent) {
            log.warn('Usage: env_manager set <key> <value>');
          }
          return 1;
        }
        const [key, ...valueParts] = remainingArgs;
        const newValue = valueParts.join(' ');
        const newEnvVars = setValue(envVars, options.prefix, key, newValue);
        writeEnvFile(options.envFile, newEnvVars);
        if (!options.silent) {
          log.info(`Set ${options.prefix}${key.toUpperCase()} to: "${newValue}"`);
        }
        break;
      }

      case 'list':
      case 'ls': {
        const vars = listVars(envVars, options.prefix);
        vars.forEach(({ key, value }) => {
          const padding = ' '.repeat(Math.max(0, 30 - key.length));
          console.log(`${key}${padding}${value}`);
        });
        break;
      }

      case 'reset': {
        // Implementation would depend on default.env handling
        if (!options.silent) {
          log.warn('Reset not implemented in JS version');
        }
        break;
      }

      case 'update': {
        // Implementation would depend on merge logic
        if (!options.silent) {
          log.warn('Update not implemented in JS version');
        }
        break;
      }

      default: {
        if (!options.silent) {
          log.warn('Usage: env_manager [--silent] [--env-file <file>] [--prefix <prefix>] {get|set|ls|list|reset|update} [key] [value]');
        }
        return 1;
      }
    }
    return 0;
  } catch (err) {
    if (!options.silent) {
      log.error(err.message);
    }
    return 1;
  }
}

if (import.meta.main) {
  const args = getArgs();
  process.exit(await envManager(args));
}