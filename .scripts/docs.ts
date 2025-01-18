// Sync for wiki <-> docs in the repo
// deno run -A ./.scripts/docs.ts

const wikiLocation = "../harbor.wiki"
const docsLocation = "./docs"

async function copyDocsFromWiki() {
  const wikiPath = Deno.realPathSync(wikiLocation)
  const wikiFiles = Deno.readDirSync(wikiPath)
  for (const file of wikiFiles) {
    if (file.isFile) {
      const source = `${wikiPath}/${file.name}`
      const dest = `${docsLocation}/${file.name}`
      await Deno.copyFile(source, dest)
    }
  }

  // Rename Home.md to README.md for the main page
  const homePath = `${docsLocation}/Home.md`
  const readmePath = `${docsLocation}/README.md`
  await Deno.rename(homePath, readmePath)
}

async function copyDocsToWiki() {
  const docsPath = Deno.realPathSync(docsLocation)
  const docsFiles = Deno.readDirSync(docsPath)
  for (const file of docsFiles) {
    if (file.isFile) {
      const source = `${docsPath}/${file.name}`
      const dest = `${wikiLocation}/${file.name}`
      await Deno.copyFile(source, dest)
    }
  }

  // Rename README.md to Home.md for the main page
  const readmePath = `${wikiLocation}/README.md`
  const homePath = `${wikiLocation}/Home.md`
  await Deno.rename(readmePath, homePath)

  // Remove README.md
  await Deno.remove(readmePath)
}

// await copyDocsFromWiki()
// await copyDocsToWiki()
