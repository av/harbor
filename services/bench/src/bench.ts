import { config } from "./config.ts";
import { BenchRunner } from "./runner.ts";
import { log } from "./log.ts";

async function main() {
  log(`
░█▀▄░█▀▀░█▀█░█▀▀░█░█
░█▀▄░█▀▀░█░█░█░░░█▀█
░▀▀░░▀▀▀░▀░▀░▀▀▀░▀░▀
  `);

  const runner = await BenchRunner.init(config);
  console.table(runner.scenarios);

  await runner.run();
  await runner.eval();
}

async function handleSignal() {
  log("Interrupted");
  Deno.exit(0);
}

main().catch(console.error);

Deno.addSignalListener("SIGINT", handleSignal);
Deno.addSignalListener("SIGTERM", handleSignal);
