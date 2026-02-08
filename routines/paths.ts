import fs from 'node:fs'
import path from 'node:path'

// Deno's equivalent
const __dirname = import.meta.dirname;

export const paths = {
  home: path.resolve(__dirname, '..'),
  routines: path.resolve(__dirname),
  services: path.resolve(__dirname, '..', 'services'),
  mergedYaml: '__harbor.yml',
  tools: path.resolve(__dirname, '..', 'tools'),
  toolsConfig: '__tools.yml',
  toolsCompose: 'compose.tools.yml',
  currentProfile: '.env',
}

export async function listComposeFiles(dir = paths.services) {
  const files = await fs.promises.readdir(dir);

  return files
    .filter((file: string) => file.match(/compose\..+\.yml/))
    .sort((a: string, b: string) => {
      const dotsInA = (a.match(/\./g) || []).length;
      const dotsInB = (b.match(/\./g) || []).length;
      if (dotsInA !== dotsInB) return dotsInA - dotsInB;
      return a.localeCompare(b);
    });
}

/**
 * List TypeScript compose modules in the given directory.
 * Mirrors listComposeFiles() but for .ts files.
 */
export async function listComposeModules(dir = paths.services) {
  const files = await fs.promises.readdir(dir);

  return files
    .filter((file: string) => file.match(/compose\..+\.ts$/))
    .sort((a: string, b: string) => {
      const dotsInA = (a.match(/\./g) || []).length;
      const dotsInB = (b.match(/\./g) || []).length;
      if (dotsInA !== dotsInB) return dotsInA - dotsInB;
      return a.localeCompare(b);
    });
}