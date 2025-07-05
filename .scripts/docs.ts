// Sync for wiki <-> docs in the repo
// h dev docs
// deno run -A ./.scripts/docs.ts

import remarkParse from "npm:remark-parse";
import remarkStringify from "npm:remark-stringify";
import { unified } from "npm:unified";
import { visit } from "npm:unist-util-visit";

import { copyDocsToApp } from './docs-to-app.ts'

const wikiUrl = 'https://github.com/av/harbor/wiki'
const wikiLocation = "../harbor.wiki";
const docsLocation = "./docs";
const appLocation = "./app/src/docs"

const targets = {
  "./docs/5.2.-Harbor-Boost.md": "./boost/README.md",
  "./docs/2.3.28-Satellite&colon-Promptfoo.md": "./promptfoo/README.md",
};

const docgenTargets = {
  'harbor run boost uv run config.py': './docs/5.2.2-Harbor-Boost-Configuration.md',
  'harbor run boost uv run mods.py': './docs/5.2.3-Harbor-Boost-Modules.md',
}

main().catch(console.error);

async function main() {
  // Must be first to be ready for the copy
  await renderServiceIndex()
  await Promise.all([
    copyDocsToWiki(),
    copyDocsToApp(),
    copyTargets(),
    docgen(),
  ])
}

async function copyDocsFromWiki() {
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
  const docsFiles = Array.from(Deno.readDirSync(docsPath));
  const processor = await createProcessor([relativeLinksToWiki])
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
  const processor = await createProcessor([replaceRelativeLinks])

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
  processor: (any) => Promise<any>
) {
  const sourceContent = await Deno.readTextFile(source);
  const destContent = await processor(sourceContent);

  await Deno.writeTextFile(dest, destContent);
}

function replaceRelativeLinks() {
  return (tree: any) => {
    visit(tree, "link", (node: any) => {
      if (node.url.startsWith("./")) {
        node.url = node.url.replace("./", "../docs/");
      }
    });

    visit(tree, "image", (node: any) => {
      if (node.url.startsWith("./")) {
        node.url = node.url.replace("./", "../docs/");
      }
    });
  };
}

function relativeLinksToWiki() {
  return (tree: any) => {
    visit(tree, "link", (node: any) => {
      if (node.url.startsWith('./') && node.url.includes('.md')) {
        node.url = node.url.replace(".md", "").replace("./", wikiUrl + '/');
      }
    });
  };
}

async function createProcessor(
  plugins: any[] = []
) {
  let processor = unified()
    .use(remarkParse)

  for (const plugin of plugins) {
    processor = processor.use(plugin);
  }

  processor = processor.use(remarkStringify, {
    bullet: "-",
    handlers: {
      text: textHandle,
    },
    resourceLink: true,
  })
  processor = await processor;

  return (doc) => processor.process(doc);
}

function unsafeFilter(rule: Unsafe): boolean {
  // We don't want to escape '[' as it's wildly used in - checkbox, backlink, GitHub notes.
  if (rule.character === '[') {
    return false
  }

  if (rule.character === '&') {
    return false
  }

  return true
}

export function text(node, _, state, info) {
  return state.safe(node.value, info)
}

function textHandle(node, parent, context, safeOptions) {
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
  const byTag = (tag: typeof tags) =>
    services
      .filter((s) => (s.tags ?? []).includes(tag))
      .sort((a, b) => a.name.localeCompare(b.name));

  const frontends = byTag(tags.frontend);
  const backends = byTag(tags.backend);
  const satellites = byTag(tags.satellite);

  const renderService = (s) => `
- [${s.name}](${s.wikiUrl}) <span style="opacity: 0.5;">${s.tags.map((t) => `\`${t}\``).join(', ')}</span><br/>
${s.tooltip}`

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

async function docgen() {
  await Promise.all(
    Object.entries(docgenTargets).map(async ([cmd, dest]) => {
      console.debug(`Rendering target: ${cmd} -> ${dest}`);
      const process = Deno.run({
        cmd: cmd.split(" "),
        stdout: "piped",
        stderr: "piped",
      });

      const [status, stdout, stderr] = await Promise.all([
        process.status(),
        process.output(),
        process.stderrOutput(),
      ]);

      if (!status.success) {
        const error = new TextDecoder().decode(stderr);
        console.error(`Error running command "${cmd}": ${error}`);
        throw new Error(`Command failed: ${error}`);
      }

      const output = new TextDecoder().decode(stdout).trim();
      if (!output) {
        console.warn(`No output from command "${cmd}"`);
        return;
      }

      await Deno.writeTextFile(dest, output);
      console.debug(`Rendered target: ${cmd} -> ${dest}`);
    })
  );
}
