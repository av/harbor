import * as yaml from "jsr:@std/yaml";
import { deepMerge } from "jsr:@std/collections/deep-merge";

import { paths } from "./paths";
import { consumeFlagArg, errorToString, getArgs, log } from "./utils";
import { composeCommand, resolveComposeFiles } from "./docker";
import { loadTransformedUpstream } from "./upstream";

export async function mergeComposeFiles(args) {
  let shouldMerge = !consumeFlagArg(args, ["--no-merge"]);
  const sourceFiles = await resolveComposeFiles(args);
  let targetFiles = []

  if (shouldMerge) {
    // Load compose file contents
    const contents = await Promise.all(
      sourceFiles.map(async (file) => yaml.parse(await Deno.readTextFile(file)))
    );

    // Check for upstream services and load their transformed compose
    const upstreamContents = await loadUpstreamComposeForServices(args);

    // Merge all files into a single file
    // to avoid docker-compose own merge logic that is very slow for
    // larger amount of files
    const allContents = [...upstreamContents, ...contents];
    const merged = allContents.reduce((acc, next) => deepMerge(acc, next), {});
    await Deno.writeTextFile(paths.mergedYaml, yaml.stringify(merged))
    targetFiles.push(`${paths.home}/${paths.mergedYaml}`);
  } else {
    // Keep files as they are
    targetFiles = sourceFiles.map((file) => `${paths.home}/${file}`);
  }

  console.log(await composeCommand(
    targetFiles.map((file) => `-f ${file}`).join(' '),
  ));
}

/**
 * Load transformed upstream compose files for requested services
 */
async function loadUpstreamComposeForServices(args: string[]): Promise<object[]> {
  const upstreamContents: object[] = [];

  for (const arg of args) {
    // Skip flags and capabilities
    if (arg.startsWith("-") || arg.startsWith("*")) {
      continue;
    }

    const transformed = await loadTransformedUpstream(arg);
    if (transformed) {
      log.debug(`Loaded upstream compose for service: ${arg}`);
      upstreamContents.push(transformed);
    }
  }

  return upstreamContents;
}

if (import.meta.main === true) {
  const args = getArgs();
  mergeComposeFiles(args).catch((err) => log(errorToString(err)));
}
