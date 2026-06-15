/// <reference lib="deno.ns" />

// Entry point for `harbor dev lint`.
//
// The orchestrator and its passes live under .scripts/lint/ — this file is just
// the dispatch hook wired into run_harbor_dev() in harbor.sh (which runs
// .scripts/<name>.ts). Passes: shellcheck, bash project rules, compose, boost.

await import("./lint/run.ts");
