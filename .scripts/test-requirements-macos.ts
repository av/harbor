/// <reference lib="deno.ns" />

// Entry point for `harbor dev test-requirements-macos`.
//
// The tests themselves are bash (they stub PATH commands and source
// requirements.sh), so this file just dispatches to the sibling .sh script,
// forwarding args (e.g. --no-bash32 to skip the bash 3.2 container pass).

const scriptDir = new URL(".", import.meta.url).pathname;

const cmd = new Deno.Command("bash", {
  args: [`${scriptDir}test-requirements-macos.sh`, ...Deno.args],
  stdout: "inherit",
  stderr: "inherit",
});

Deno.exit((await cmd.output()).code);
