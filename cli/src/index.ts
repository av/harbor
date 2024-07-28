import { argv } from 'zx';
import * as workspace from './lib/workspace';

const commands = {
  help,
  init,
  update,
};

main().catch(console.error);

////////////////////////////////////////////////////////////////////////////////

async function main() {
  const command = argv._[0];
  if (command in commands) {
    await commands[command]();
  } else {
    console.log('>>> Unknown command:', command)
    await help();
  }
}

async function help() {
  console.log(`
harbor <command> [options]

Commands:
  init   - Initialize harbor workspace in the current directory
  update - Update harbor to the latest version from GitHub
`)
}

async function init() {
  await workspace.init();
}

async function update() {
  await workspace.update();
}