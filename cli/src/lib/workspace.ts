import { $, fs as zfs, cd, spinner } from 'zx';
import fs from 'fs/promises';

import { paths } from './paths';
import { config } from './config';

export async function checkInit() {
  try {
    await fs.access(paths.git, fs.constants.F_OK);
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

export async function printVersionInfo() {
  await ensureInit();
  const pkg = await readPkg();
  console.log(`Harbor v${pkg.version}`);
}

export async function init() {
  const isDone = await checkInit();

  if (!isDone) {
    await spinner('Initializing Harbor workspace from GitHub...', async () => {
      await cd(paths.root);
      await $`git clone ${config.harbor.git} .`;
    });
    console.log('Harbor workspace initialized.')
  } else {
    console.log(`
Harbor workspace is already initialized.
Run 'harbor update' to update to the latest version.
    `)
  }

  await printVersionInfo();
}

export async function update() {
  await ensureInit();
  await spinner('Updating Harbor workspace from GitHub...', async () => {
    await cd(paths.root);
    await $`git pull`;
  });
  console.log('Harbor workspace updated.')
  await printVersionInfo();
}


let pkg;

export async function readPkg() {
  if (!pkg) {
    pkg = zfs.readJSON(paths.pkg);
  }

  return pkg;
}