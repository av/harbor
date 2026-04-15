import { promises as fs } from 'node:fs';
import { join } from 'node:path';

import { createDocsPageSet, rewriteLinkForApp } from './docs-links.ts';

const docsLocation = "./docs";
const appLocation = "./app/src/docs"

export async function copyDocsToApp() {
  console.debug("Copying docs to app...");

  try {
    // Get absolute path for docs location
    const docsPath = await fs.realpath(docsLocation);

    // Read all files from the docs directory
    const docsFiles = await fs.readdir(docsPath, { withFileTypes: true });
    const docsPages = createDocsPageSet(
      docsFiles.filter((file) => file.isFile()).map((file) => file.name),
    );

    // Create app directory if it doesn't exist
    await fs.mkdir(appLocation, { recursive: true });

    for (const existingFile of await fs.readdir(appLocation, { withFileTypes: true })) {
      if (!existingFile.isFile()) {
        continue;
      }

      await fs.rm(join(appLocation, existingFile.name));
    }

    // Copy each file from docs to app
    for (const file of docsFiles) {
      if (file.isFile()) {
        const source = join(docsPath, file.name);
        const dest = join(appLocation, file.name);

        if (file.name.endsWith('.md')) {
          const sourceContent = await fs.readFile(source, 'utf8');
          const destContent = rewriteMarkdownLinksForApp(sourceContent, docsPages);
          await fs.writeFile(dest, destContent, 'utf8');
        } else {
          await fs.copyFile(source, dest);
        }
      }
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error(`Error copying docs to app: ${message}`);
    throw error;
  }
}

export function rewriteMarkdownLinksForApp(
  content: string,
  docsPages: ReadonlySet<string>,
) {
  return content.replaceAll(/(?<prefix>!?(?:\[[^\]]*\]|\[[^\]]*\]\[[^\]]*\])\()(?<url>[^)\s]+)(?<suffix>(?:\s+"[^"]*")?\))/g, (...args) => {
    const groups = args.at(-1) as Record<string, string>;
    const rewrittenUrl = rewriteLinkForApp(groups.url, docsPages);
    return `${groups.prefix}${rewrittenUrl}${groups.suffix}`;
  });
}

if (import.meta.main) {
  copyDocsToApp();
}
