import { ConfigValue, StringListParser } from './config';
import { cachedReadFile, CONFIG_PREFIX, decodeBashValue, encodeBashValue, log, once } from "./utils";
import { paths } from './paths';
import { EnvJsonValueSetter, EnvKey, EnvValuePointer, EnvValueSetter } from './types';

export const TOOLS_CONFIG_KEY = 'tools';

export class EnvManagerConfigValue<T> extends ConfigValue<T> {
  override async resolve() {
    this.rawValue = await getValue({
      key: this.key,
      prefix: CONFIG_PREFIX,
    });
  }
}

export const defaultCapabilities = new EnvManagerConfigValue({
  key: 'capabilities.default',
  parser: new StringListParser(),
})

export const defaultServices = new EnvManagerConfigValue({
  key: 'services.default',
  parser: new StringListParser(),
})

/**
 * Convert input config key into a Harbor profile key.
 */
export async function toEnvKey({
  key,
  prefix = CONFIG_PREFIX,
}: EnvKey) {
  const envKey = key
    .replace(/-/g, "_")
    .replace(/\./g, "_")
    .toUpperCase();

  return prefix + envKey;
}

/**
 * Get given value from the env profile.
 */
export async function getValue({
  profile = paths.currentProfile,
  prefix = CONFIG_PREFIX,
  key,
}: EnvValuePointer) {
  const finalKey = await toEnvKey({ key, prefix });
  const contents = await cachedReadFile(profile);
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

export async function setValue({
  key,
  value,
  profile = paths.currentProfile,
  prefix = CONFIG_PREFIX,
}: EnvValueSetter) {
  const finalKey = await toEnvKey({ key, prefix });
  const contents = await cachedReadFile(profile);
  const lines = contents.split("\n").map((line) => {
    const isTarget = line.startsWith(`${finalKey}=`);

    if (isTarget) {
      return `${finalKey}="${encodeBashValue(value)}"`;
    }

    return line;
  });

  await Deno.writeTextFile(profile, lines.join("\n"));
}

export async function getJsonValue(config: EnvValuePointer) {
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

export async function setJsonValue(config: EnvJsonValueSetter) {
  const json = JSON.stringify(config.value);
  await setValue({ ...config, value: json });
}

export function cachedConfig(config: EnvValuePointer) {
  return once(() => getValue(config));
}
