// Sync for wiki <-> docs in the repo
// h dev docs
// deno run -A ./.scripts/docs.ts

import remarkParse from 'npm:remark-parse'
import remarkStringify from 'npm:remark-stringify'
import { unified } from 'npm:unified'
import { visit } from 'npm:unist-util-visit'

const wikiLocation = "../harbor.wiki"
const docsLocation = "./docs"

const targets = {
  './docs/5.2.-Harbor-Boost.md': './boost/README.md',
  './docs/2.3.28-Satellite&colon-Promptfoo.md': './promptfoo/README.md',
}

main().catch(console.error)

async function main() {
  await copyDocsToWiki()
  await copyTargets()
}

async function copyDocsFromWiki() {
  const wikiPath = Deno.realPathSync(wikiLocation)
  const wikiFiles = Deno.readDirSync(wikiPath)
  for (const file of wikiFiles) {
    if (file.isFile) {
      const source = `${wikiPath}/${file.name}`
      const dest = `${docsLocation}/${toRepoFileName(file.name)}`
      await Deno.copyFile(source, dest)
    }
  }

  // Rename Home.md to README.md for the main page
  const homePath = `${docsLocation}/Home.md`
  const readmePath = `${docsLocation}/README.md`
  await Deno.rename(homePath, readmePath)
}

async function copyDocsToWiki() {
  console.debug('Copying docs to wiki...')

  const docsPath = Deno.realPathSync(docsLocation)
  const docsFiles = Deno.readDirSync(docsPath)
  for (const file of docsFiles) {
    if (file.isFile) {
      const source = `${docsPath}/${file.name}`
      const dest = `${wikiLocation}/${toWikiFileName(file.name)}`
      await Deno.copyFile(source, dest)
    }
  }

  // Rename README.md to Home.md for the main page
  const readmePath = `${wikiLocation}/README.md`
  const homePath = `${wikiLocation}/Home.md`
  await Deno.rename(readmePath, homePath)
}

function toRepoFileName(name: string) {
  return name.replaceAll(':', '&colon')
}

function toWikiFileName(name: string) {
  return name.replaceAll('&colon', ':')
}

async function copyTargets() {
  for (const [source, dest] of Object.entries(targets)) {
    console.debug(`Copying ${source} to ${dest}`)
    const processor = await unified().use(remarkParse).use(replaceRelativeLinks).use(remarkStringify)
    const sourceContent = await Deno.readTextFile(source)
    const destContent = await processor.process(sourceContent)

    await Deno.writeTextFile(dest, destContent)
  }
}

function replaceRelativeLinks() {
  return (tree: any) => {
    visit(tree, 'link', (node: any) => {
      if (node.url.startsWith('./')) {
        node.url = node.url.replace('./', '../docs/')
      }
    })

    visit(tree, 'image', (node: any) => {
      if (node.url.startsWith('./')) {
        node.url = node.url.replace('./', '../docs/')
      }
    })
  }
}