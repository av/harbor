// Add projectUrl field to service metadata from docs
// h dev add-project-urls

const docsLocation = "./docs";
const metadataFile = "./app/src/serviceMetadata.ts";

interface ParsedDoc {
  handle: string;
  projectUrl: string;
  filename: string;
}

async function parseDocFile(filePath: string): Promise<ParsedDoc | null> {
  const content = await Deno.readTextFile(filePath);
  const lines = content.split('\n').slice(0, 5);

  // First line: ### [Name](URL)
  const urlMatch = lines[0]?.match(/###\s*\[.*?\]\((https?:\/\/[^)]+)\)/);
  if (!urlMatch) {
    console.warn(`No URL found in: ${filePath}`);
    return null;
  }

  // Second/third line: > Handle: `handle`
  const handleLine = lines.find(l => l.includes('Handle:'));
  const handleMatch = handleLine?.match(/Handle:\s*`([^`]+)`/);
  if (!handleMatch) {
    console.warn(`No handle found in: ${filePath}`);
    return null;
  }

  return {
    handle: handleMatch[1],
    projectUrl: urlMatch[1],
    filename: filePath,
  };
}

async function main() {
  const docsPath = Deno.realPathSync(docsLocation);
  const docsFiles = Array.from(Deno.readDirSync(docsPath));

  // Filter to service docs (2.1.*, 2.2.*, 2.3.*)
  const serviceDocFiles = docsFiles
    .filter(f => f.isFile && /^2\.[123]\.\d+/.test(f.name))
    .map(f => `${docsPath}/${f.name}`);

  console.log(`Found ${serviceDocFiles.length} service doc files`);

  // Parse all docs
  const parsed: ParsedDoc[] = [];
  for (const file of serviceDocFiles) {
    const result = await parseDocFile(file);
    if (result) {
      parsed.push(result);
    }
  }

  console.log(`Parsed ${parsed.length} docs with handles`);

  // Read current metadata file
  let metadataContent = await Deno.readTextFile(metadataFile);

  // For each parsed doc, add projectUrl if the handle exists in metadata
  let updated = 0;
  for (const doc of parsed) {
    const handleKey = doc.handle.replace(/-/g, '');

    // Check if handle exists in metadata (look for `handle: {` pattern)
    const handlePattern = new RegExp(`['"]?${doc.handle}['"]?:\\s*\\{`, 'i');
    const altHandlePattern = new RegExp(`['"]?${handleKey}['"]?:\\s*\\{`, 'i');

    if (!handlePattern.test(metadataContent) && !altHandlePattern.test(metadataContent)) {
      console.warn(`Handle '${doc.handle}' not found in metadata`);
      continue;
    }

    // Check if projectUrl already exists for this handle
    // Find the block for this handle and check if it has projectUrl
    const blockRegex = new RegExp(
      `(['"]?${doc.handle}['"]?:\\s*\\{[^}]*?)(wikiUrl:)`,
      'is'
    );
    const altBlockRegex = new RegExp(
      `(['"]?${handleKey}['"]?:\\s*\\{[^}]*?)(wikiUrl:)`,
      'is'
    );

    const match = metadataContent.match(blockRegex) || metadataContent.match(altBlockRegex);
    if (match) {
      // Check if projectUrl already exists in this block
      const blockStart = metadataContent.indexOf(match[0]);
      const blockEnd = metadataContent.indexOf('},', blockStart);
      const block = metadataContent.slice(blockStart, blockEnd);

      if (block.includes('projectUrl:')) {
        console.log(`projectUrl already exists for '${doc.handle}'`);
        continue;
      }

      // Insert projectUrl before wikiUrl
      const insertText = `projectUrl: '${doc.projectUrl}',\n        `;
      metadataContent = metadataContent.replace(
        match[0],
        match[1] + insertText + match[2]
      );
      updated++;
      console.log(`Added projectUrl for '${doc.handle}': ${doc.projectUrl}`);
    } else {
      console.warn(`Could not find wikiUrl pattern for '${doc.handle}'`);
    }
  }

  // Write updated metadata
  await Deno.writeTextFile(metadataFile, metadataContent);
  console.log(`\nUpdated ${updated} service entries with projectUrl`);
}

main().catch(console.error);
