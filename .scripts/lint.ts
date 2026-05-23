/// <reference lib="deno.ns" />

// Entry point for `harbor dev lint`.
//
// The orchestrator and its three passes live under .scripts/lint/ — this file
// is just the dispatch hook wired into run_harbor_dev() in harbor.sh (which
// runs .scripts/<name>.ts). The previous in-file compose linter has moved to
// .scripts/lint/passes/compose.ts and is now one of three passes (shellcheck,
// bash project rules, compose).

await import("./lint/run.ts");
