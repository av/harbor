// routines/mergeComposeFiles.js (`v11.0` Executor)
//
// This Deno script reads a list of YAML file paths from standard input,
// merges them into a single Docker Compose configuration, and writes the
// result to a specified output file. It acts as a "fast worker" called by
// the Bash "planner".

import * as yaml from "jsr:@std/yaml";
import { deepMerge } from "jsr:@std/collections/deep-merge";
import { paths } from "./paths";
import { getArgs, log } from "./utils";
import { parseArgs } from "jsr:@std/cli/parse-args";
import { composeCommand, resolveComposeFiles } from "./docker";

// Custom merger function to concatenate arrays instead of replacing them.
// This is crucial for correctly merging things like `volumes` or `env_file`.
const mergeCustomizer = (a, b) => {
    if (Array.isArray(a) && Array.isArray(b)) {
        return [...a, ...b];
    }
    // Return undefined to fallback to default deep merge behavior for objects.
    return undefined;
};

async function mergeYamlFiles(filePaths, outputFile) {
    if (filePaths.length === 0) {
        console.error("No YAML files provided to merge.");
        return;
    }

    const mergedConfig = await Promise.all(
        filePaths.map(async (file) => {
            try {
                return yaml.parse(await Deno.readTextFile(file.trim()));
            } catch (e) {
                console.error(`Error reading or parsing file: ${file.trim()}`, e.message);
                return {}; // Return empty object on error to not break the chain
            }
        })
    ).then((contents) =>
        contents.reduce((acc, next) => deepMerge(acc, next, { arrays: "merge" }), {})
    );

    await Deno.writeTextFile(outputFile, yaml.stringify(mergedConfig));
    console.error(`Successfully merged ${filePaths.length} files into ${outputFile}`);
}

async function main() {
    const args = parseArgs(Deno.args, {
        string: ["output"],
        default: { output: "merged.compose.yml" },
    });

    // Read file paths from standard input.
    const stdinContent = await new Response(Deno.stdin.readable).text();
    const filePaths = stdinContent.split('\n').filter(line => line.trim() !== '');

    await mergeYamlFiles(filePaths, args.output);
}

if (import.meta.main) {
    main().catch(err => {
        console.error("An unexpected error occurred in mergeComposeFiles.js:", err);
        Deno.exit(1);
    });
}