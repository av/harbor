import * as yaml from "jsr:@std/yaml";
import { deepMerge } from "jsr:@std/collections/deep-merge";

import { paths } from "./paths";
import { consumeFlagArg, errorToString, getArgs, log } from "./utils";
import { composeCommand, resolveComposeFiles } from "./docker";

export async function mergeComposeFiles(args) {
  let shouldMerge = !consumeFlagArg(args, ["--no-merge"]);
  const sourceFiles = await resolveComposeFiles(args);
  let targetFiles = []

  if (shouldMerge) {
    // Merge all files into a single file
    // to avoid docker-compose own merge logic that is very slow for
    // larger amount of files
    const contents = await Promise.all(
      sourceFiles.map(async (file) => yaml.parse(await Deno.readTextFile(file)))
    )
    const merged = contents.reduce((acc, next) => deepMerge(acc, next), {});
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

if (import.meta.main === true) {
  const args = getArgs();
  mergeComposeFiles(args).catch((err) => log(errorToString(err)));
}
