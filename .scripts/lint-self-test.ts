/// <reference lib="deno.ns" />

// Entry point for `harbor dev lint-self-test`.
//
// The harness itself lives at .scripts/lint/self-test.ts — this file is just
// the dispatch hook wired into run_harbor_dev() in harbor.sh (which runs
// .scripts/<name>.ts). Keeping the implementation next to the fixtures and
// rules it validates co-locates every piece of the self-test feedback loop.

await import("./lint/self-test.ts");
