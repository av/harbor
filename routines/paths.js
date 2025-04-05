import fs from 'node:fs'
import path from 'node:path'

// Deno's equivalent
const __dirname = import.meta.dirname;

export const paths = {
  home: path.resolve(__dirname, '..'),
  routines: path.resolve(__dirname),
  mergedYaml: '__harbor.yml',
  tools: path.resolve(__dirname, '..', 'tools'),
  toolsConfig: '__tools.yml',
  toolsCompose: 'compose.tools.yml',
  currentProfile: '.env',
}

export async function listComposeFiles() {
  const files = await fs.promises.readdir(paths.home);
  return files
    .filter((file) => file.match(/compose\..+\.yml/))
    .sort((a, b) => {
      const dotsInA = (a.match(/\./g) || []).length;
      const dotsInB = (b.match(/\./g) || []).length;
      return dotsInA - dotsInB;
    });
}