import * as yaml from "jsr:@std/yaml";
import { deepMerge } from "jsr:@std/collections/deep-merge";

import { paths } from "./paths";
import { getArgs, log } from "./utils";
import { composeCommand, resolveComposeFiles } from "./docker";

export async function mergeComposeFiles(args) {
  const sourceFiles = await resolveComposeFiles(args);

  // Merge all files into a single file
  // to avoid docker-compose own merge logic that is very slow for
  // larger amount of files
  await Promise.all(
    sourceFiles.map(async (file) => yaml.parse(await Deno.readTextFile(file)))
  )
    .then((contents) =>
      contents.reduce((acc, next) => deepMerge(acc, next), {})
    )
    .then((merged) =>
      Deno.writeTextFile(paths.mergedYaml, yaml.stringify(merged))
    );

  // Communicate the command back to bash
  console.log(composeCommand(`-f ${paths.home}/${paths.mergedYaml}`));
}

if (import.meta.main === true) {
  const args = getArgs();
  mergeComposeFiles(args).catch((err) => log(err));
}
