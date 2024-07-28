import { $, cd, spinner } from 'zx';
import fs from 'fs/promises';

import { paths } from './paths';
import { config } from './config';

export async function checkInit() {
  try {
    await fs.access(paths.workspaceGit, fs.constants.F_OK);
    return true;
  } catch (e) {
    return false;
  }
}

export async function ensureInit() {
  if (!(await checkInit())) {
    throw new Error('Harbor workspace is not initialized. Initialize it with `harbor init`.');
  }
}

export async function version() {
  await ensureInit();
  await cd(paths.workspace);
  return (await $`cat package.json | jq .version`).stdout;
}

export async function init() {
  const isDone = await checkInit();

  if (!isDone) {
    await spinner('Initializing Harbor workspace from GitHub...', async () => {
      await cd(paths.workspace);
      await $`git clone ${config.harbor.git} .`;
    });
    console.log('Harbor workspace initialized.')
  } else {
    console.log(`
Harbor workspace is already initialized.
Run 'harbor update' to update to the latest version.
    `)
  }

  console.log(await version());
  // await $`git clone ${config.harbor.git} ${paths.workspace}`;

  // await echo(
  //   await $`ls ${paths.workspace}`
  // )

  // echo(await $`id -u`);
  // await echo(await $`pwd`);
}

export async function update() {
  await ensureInit();
  await spinner('Updating Harbor workspace from GitHub...', async () => {
    await cd(paths.workspace);
    await $`git pull`;
  });
  console.log('Harbor workspace updated.')
  console.log(await version());
}