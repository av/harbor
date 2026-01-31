import { LLMConfig } from "./llm.ts";
import { parseArgs } from "./utils.ts";

const args = parseArgs(Deno.args);

if (!args.name) {
    throw new Error("Specify '--name' argument to run the bench");
}

export const config = {
    name: `${new Date().toISOString()}-${args.name}`,
    variants: Deno.env.get('HARBOR_BENCH_VARIANTS'),
    parallel: parseInt(Deno.env.get('HARBOR_BENCH_PARALLEL')) || 1,
    output: '/app/results',
    tasks: '/app/tasks.yml',
    debug: Deno.env.get('HARBOR_BENCH_DEBUG') === 'true',
    llm: {
        model: Deno.env.get('HARBOR_BENCH_MODEL'),
        apiUrl: Deno.env.get('HARBOR_BENCH_API'),
        apiKey: Deno.env.get('HARBOR_BENCH_API_KEY'),
    } as LLMConfig,
    judge: {
        model: Deno.env.get('HARBOR_BENCH_JUDGE'),
        apiUrl: Deno.env.get('HARBOR_BENCH_JUDGE_API'),
        apiKey: Deno.env.get('HARBOR_BENCH_JUDGE_API_KEY'),
        prompt: Deno.env.get('HARBOR_BENCH_JUDGE_PROMPT') ?? 'default',
        max_tokens: Deno.env.get('HARBOR_BENCH_JUDGE_MAX_TOKENS') ?? 2048,
        temperature: 0,
        seed: 42,
    } as LLMConfig,
};

export type BenchConfig = typeof config;
