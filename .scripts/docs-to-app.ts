import { promises as fs } from 'node:fs';
import { join } from 'node:path';

const docsLocation = "./docs";
const appLocation = "./app/src/docs"

export async function copyDocsToApp() {
  console.debug("Copying docs to app...");

  try {
    // Get absolute path for docs location
    const docsPath = await fs.realpath(docsLocation);

    // Read all files from the docs directory
    const docsFiles = await fs.readdir(docsPath, { withFileTypes: true });

    // Create app directory if it doesn't exist
    await fs.mkdir(appLocation, { recursive: true });

    // Copy each file from docs to app
    for (const file of docsFiles) {
      if (file.isFile()) {
        const source = join(docsPath, file.name);
        const dest = join(appLocation, file.name);

        await fs.copyFile(source, dest);
      }
    }
  } catch (error) {
    console.error(`Error copying docs to app: ${error.message}`);
    throw error;
  }
}

if (import.meta.main) {
  copyDocsToApp();
}