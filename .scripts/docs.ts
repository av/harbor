/// <reference lib="deno.ns" />

// Sync for wiki <-> docs in the repo
// h dev docs
// deno run -A ./.scripts/docs.ts

import remarkParse from "remark-parse";
import remarkStringify from "remark-stringify";
import { unified } from "unified";
import { visit } from "unist-util-visit";

import { createDocsPageSet, rewriteLinkForPackageReadme, rewriteLinkForWiki } from './docs-links.ts'
import { copyDocsToApp } from './docs-to-app.ts'

const wikiUrl = 'https://github.com/av/harbor/wiki'
const wikiLocation = "../harbor.wiki";
const docsLocation = "./docs";
const targets = {
  "./docs/5.2.-Harbor-Boost.md": "./boost/README.md",
  "./docs/2.3.28-Satellite&colon-Promptfoo.md": "./promptfoo/README.md",
};

const docgenTargets = {
  '/bin/bash ./harbor.sh run boost uv run config.py': './docs/5.2.2-Harbor-Boost-Configuration.md',
  '/bin/bash ./harbor.sh run boost uv run mods.py': './docs/5.2.3-Harbor-Boost-Modules.md',
}

/** Manual sections in 5.2.3 — not emitted by mods.py; preserved across regen. */
export const BOOST_MODULES_MANUAL_HEADINGS = [
  'Web search requirement',
  'Workspace bind mount',
  'Agentic coding workflow presets',
] as const;

export function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

export function extractMarkdownSection(doc: string, heading: string): string | null {
  const pattern = new RegExp(
    `^## ${escapeRegExp(heading)}\\n([\\s\\S]*?)(?=^## |\\Z)`,
    'm',
  );
  const match = doc.match(pattern);
  if (!match) {
    return null;
  }

  return `## ${heading}\n${match[1].trimEnd()}\n`;
}

export function extractManualSections(
  doc: string,
  headings: readonly string[] = BOOST_MODULES_MANUAL_HEADINGS,
): string[] {
  return headings
    .map((heading) => extractMarkdownSection(doc, heading))
    .filter((section): section is string => section !== null);
}

export function mergeBoostModulesManualSections(
  generated: string,
  manualSections: string[],
  insertBeforeHeading = 'clarity',
): string {
  if (manualSections.length === 0) {
    return generated;
  }

  const manualBlock = `\n${manualSections.join('\n')}\n`;
  const insertBefore = new RegExp(`^## ${escapeRegExp(insertBeforeHeading)}\\n`, 'm');

  if (!insertBefore.test(generated)) {
    console.warn(
      `Could not find "## ${insertBeforeHeading}" in generated Boost modules doc; appending manual sections.`,
    );
    return `${generated.trimEnd()}${manualBlock}`;
  }

  return generated.replace(insertBefore, `${manualBlock}\n## ${insertBeforeHeading}\n`);
}

if (import.meta.main) {
  main().catch(console.error);
}

async function main() {
  await Promise.all([
    renderServiceIndex(),
    docgen(),
  ])

  await Promise.all([
    copyDocsToWiki(),
    copyDocsToApp(),
    copyTargets(),
  ])
}

async function _copyDocsFromWiki() {
  const wikiPath = Deno.realPathSync(wikiLocation);
  const wikiFiles = Deno.readDirSync(wikiPath);
  for (const file of wikiFiles) {
    if (file.isFile) {
      const source = `${wikiPath}/${file.name}`;
      const dest = `${docsLocation}/${toRepoFileName(file.name)}`;
      await Deno.copyFile(source, dest);
    }
  }

  // Rename Home.md to README.md for the main page
  const homePath = `${docsLocation}/Home.md`;
  const readmePath = `${docsLocation}/README.md`;
  await Deno.rename(homePath, readmePath);
}

async function copyDocsToWiki() {
  console.debug("Copying docs to wiki...");

  const docsPath = Deno.realPathSync(docsLocation);
  const wikiPath = Deno.realPathSync(wikiLocation);
  await clearRootFiles(wikiPath);
  const docsFiles = Array.from(Deno.readDirSync(docsPath));
  const docsPages = createDocsPageSet(
    docsFiles.filter((file) => file.isFile).map((file) => file.name),
  );
  const processor = await createProcessor([() => relativeLinksToWiki(docsPages)])
  let copied = 0;


  for (const file of docsFiles) {
    if (file.isFile) {
      const source = `${docsPath}/${file.name}`;
      const dest = `${wikiLocation}/${toWikiFileName(file.name)}`;

      if (source.endsWith('.md')) {
        await copyWithProcessor(source, dest, processor);
      } else {
        await Deno.copyFile(source, dest);
      }

      console.log(`wiki: [${++copied}/${docsFiles.length}]`)

    }
  }

  // Rename README.md to Home.md for the main page
  const readmePath = `${wikiLocation}/README.md`;
  const homePath = `${wikiLocation}/Home.md`;
  await Deno.rename(readmePath, homePath);
}

function toRepoFileName(name: string) {
  return name.replaceAll(":", "&colon");
}

function toWikiFileName(name: string) {
  return name.replaceAll("&colon", ":");
}

async function copyTargets() {
  console.debug("Copying targets...");
  const docsPages = createDocsPageSet(
    Array.from(Deno.readDirSync(Deno.realPathSync(docsLocation)))
      .filter((file) => file.isFile)
      .map((file) => file.name),
  );
  const processor = await createProcessor([() => replaceRelativeLinks(docsPages)])

  for (const [source, dest] of Object.entries(targets)) {
    await copyWithProcessor(
      source,
      dest,
      processor,
    )
  }
}

async function copyWithProcessor(
  source: string,
  dest: string,
  processor: (doc: string) => Promise<string>
) {
  const sourceContent = await Deno.readTextFile(source);
  const destContent = await processor(sourceContent);

  // Ensure destination directory exists before writing
  const dir = dest.split('/').slice(0, -1).join('/');
  if (dir && !Array.from(Deno.readDirSync('.')).some(d => d.name === dir && d.isDirectory)) {
    await Deno.mkdir(dir, { recursive: true });
  }

  await Deno.writeTextFile(dest, destContent);
}

type UrlNode = {
  url: string;
};

function replaceRelativeLinks(docsPages: ReadonlySet<string>) {
  return (tree: unknown) => {
    visit(tree as Parameters<typeof visit>[0], "link", (node: unknown) => {
      const urlNode = node as UrlNode;
      urlNode.url = rewriteLinkForPackageReadme(urlNode.url, docsPages);
    });

    visit(tree as Parameters<typeof visit>[0], "image", (node: unknown) => {
      const urlNode = node as UrlNode;
      urlNode.url = rewriteLinkForPackageReadme(urlNode.url, docsPages);
    });
  };
}

function relativeLinksToWiki(docsPages: ReadonlySet<string>) {
  return (tree: unknown) => {
    visit(tree as Parameters<typeof visit>[0], "link", (node: unknown) => {
      const urlNode = node as UrlNode;
      urlNode.url = rewriteLinkForWiki(urlNode.url, docsPages, wikiUrl);
    });
  };
}

function createProcessor(
  plugins: Array<() => (tree: unknown) => void> = []
) {
  let processor = unified()
    .use(remarkParse)

  for (const plugin of plugins) {
    processor = processor.use(plugin);
  }

  const stringifyOptions = {
    bullet: "-",
    handlers: {
      text: textHandle,
    },
    resourceLink: true,
  };
  const stringifierProcessor = processor.use(
    remarkStringify as never,
    stringifyOptions as never,
  );

  return async (doc: string) => normalizeSerializedMarkdown(String(await stringifierProcessor.process(doc)));
}

export function normalizeSerializedMarkdown(doc: string) {
  return doc
    .replaceAll("\\&colon;", "&colon;")
    .replaceAll("\\&colon", "&colon");
}

type UnsafeRule = {
  character?: string;
};

type TextNode = {
  value: string;
};

type TextState = {
  unsafe: UnsafeRule[];
  safe: (value: string, info: unknown) => string;
};

function unsafeFilter(rule: UnsafeRule): boolean {
  // We don't want to escape '[' as it's wildly used in - checkbox, backlink, GitHub notes.
  if (rule.character === '[') {
    return false
  }

  if (rule.character === '&') {
    return false
  }

  return true
}

export function text(node: TextNode, _: unknown, state: TextState, info: unknown) {
  return state.safe(node.value, info)
}

export async function clearRootFiles(dirPath: string) {
  for await (const entry of Deno.readDir(dirPath)) {
    if (!entry.isFile) {
      continue;
    }

    await Deno.remove(`${dirPath}/${entry.name}`);
  }
}

function textHandle(
  node: TextNode,
  parent: unknown,
  context: TextState,
  safeOptions: unknown,
) {
  return text(
    node,
    parent,
    { ...context, unsafe: context.unsafe.filter(unsafeFilter) },
    safeOptions,
  )
}

async function renderServiceIndex() {
  console.debug("Rendering service index...");
  const metadata = await import("../app/src/serviceMetadata.ts");

  const services = Object.entries(metadata.serviceMetadata).map(
    ([handle, s]) => ({
      handle,
      ...s,
      name: s.name ?? handle,
      tooltip: s.tooltip ?? "",
    })
  )
    .filter((s) => !!s.wikiUrl && !!s.name);
  const tags = metadata.HST;
  const byTag = (tag: string) =>
    services
      .filter((s) => (s.tags ?? []).some((serviceTag) => serviceTag === tag))
      .sort((a, b) => a.name.localeCompare(b.name));

  const frontends = byTag(tags.frontend);
  const backends = byTag(tags.backend);
  const satellites = byTag(tags.satellite);

  const renderService = (
    s: { name: string; tooltip: string; wikiUrl?: string; logo?: string; tags?: string[] },
  ) => {
    const logoImg = s.logo
      ? `<img src="${s.logo}" alt="${s.name} logo" width="12" height="12" /> `
      : '';
    const serviceTags = s.tags ?? [];
    const tags = `<span style="opacity: 0.5;">${serviceTags.map((t: string) => `\`${t}\``).join(', ')}</span>`;
    const serviceLink = `<a href="${s.wikiUrl ?? '#'}">${logoImg}${s.name}</a>`;

    return `
- ${serviceLink} ${tags}<br/>
${s.tooltip}`;
  };

  const indexTemplate = `
Various services that are integrated with Harbor. The link in the service name will lead you to a dedicated page in Harbor's wiki with details on getting started with the service.

# Frontends

This section covers services that can provide you with an interface for interacting with the language models.
${frontends.map(renderService).join("\n")}

# Backends

This section covers services that provide the LLM inference capabilities.
${backends.map(renderService).join("\n")}

# Satellites

Additional services that can be integrated with various Frontends and Backends to enable more features.
${satellites.map(renderService).join("\n")}
  `;

  await Deno.writeTextFile(
    "./docs/2.-Services.md",
    indexTemplate
  );
}

async function readExistingDoc(dest: string): Promise<string | null> {
  try {
    return await Deno.readTextFile(dest);
  } catch (error) {
    if (error instanceof Deno.errors.NotFound) {
      return null;
    }
    throw error;
  }
}

async function docgen() {
  await Promise.all(
    Object.entries(docgenTargets).map(async ([cmd, dest]) => {
      console.debug(`Rendering target: ${cmd} -> ${dest}`);
      const existingDoc = await readExistingDoc(dest);
      const manualSections = dest === './docs/5.2.3-Harbor-Boost-Modules.md' && existingDoc
        ? extractManualSections(existingDoc)
        : [];

      const commandParts = cmd.split(" ");
      const process = new Deno.Command(commandParts[0], {
        args: commandParts.slice(1),
        stdout: "piped",
        stderr: "piped",
      });

      const { code, success, stdout, stderr } = await process.output();

      if (!success) {
        const error = new TextDecoder().decode(stderr);
        console.error(`Error running command "${cmd}" (exit ${code}): ${error}`);
        throw new Error(`Command failed: ${error}`);
      }

      let output = new TextDecoder().decode(stdout).trim();
      if (!output) {
        console.warn(`No output from command "${cmd}"`);
        return;
      }

      if (manualSections.length > 0) {
        output = mergeBoostModulesManualSections(output, manualSections);
        console.debug(
          `Preserved ${manualSections.length} manual section(s) in ${dest}`,
        );
      }

      await Deno.writeTextFile(dest, `${output}\n`);
      console.debug(`Rendered target: ${cmd} -> ${dest}`);
    })
  );
}
