import { config } from "./config.ts";
import { BenchRunner } from "./runner.ts";

async function main() {
  console.log(`
░█▀▄░█▀▀░█▀█░█▀▀░█░█
░█▀▄░█▀▀░█░█░█░░░█▀█
░▀▀░░▀▀▀░▀░▀░▀▀▀░▀░▀
  `)
  const runner = await BenchRunner.init(config);
  console.table(runner.scenarios);

  await runner.run();
  await runner.eval();
}

main().catch(console.error);
