import { deepMerge } from "jsr:@std/collections/deep-merge";
import * as yaml from "jsr:@std/yaml";

import { log } from "./utils";

/**
 * Read a YAML config file from a given path.
 *
 * @param {string} path - Path to the YAML file.
 * @param {any} defaultValue - Value to return if file doesn't exist.
 *
 * @returns {Promise<any>} - Parsed YAML content or default value if file not found.
 */
export async function readYamlConfig(path, defaultValue = {}) {
  return Deno.readTextFile(path)
    .then((contents) => yaml.parse(contents))
    .catch((e) => {
      if (e instanceof Deno.errors.NotFound) {
        return defaultValue;
      }

      if (e instanceof SyntaxError) {
        log.error(`Invalid YAML file at ${path}: ${e}`);
      } else {
        log.error(`Failed to read YAML file at ${path}: ${e}`);
      }

      throw e;
    });
}

/**
 * Merges given content into a YAML config file at a given location.
 *
 * @param {string} path - Path to the YAML file, if it doesn't exist, it will be created.
 * @param {any} content - Content to merge into the YAML file.
 *
 * @returns {Promise<any>} - The merged content.
 */
export async function mergeYamlConfig(path, content) {
  const existing = await readYamlConfig(path, {});
  const merged = deepMerge(existing, content);
  const mergedYaml = yaml.stringify(merged);
  await Deno.writeTextFile(path, mergedYaml);

  log.debug(`Merged YAML config at ${path}`);
  return merged;
}
