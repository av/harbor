import { config } from "./config.ts";
import { BenchRunner } from "./runner.ts";

async function main() {
  console.log(`
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
  console.info("Interrupted");
  Deno.exit(0);
}

main().catch(console.error);

Deno.addSignalListener("SIGINT", handleSignal);
Deno.addSignalListener("SIGTERM", handleSignal);
