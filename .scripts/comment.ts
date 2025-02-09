// deno run -A ./.scripts/comment.ts
// h dev comment

import * as yaml from 'jsr:@std/yaml';

async function main() {
  const files = Deno.readDirSync('.')
  for (const file of files) {
    if (file.isFile && file.name.endsWith('.yml')) {
      await processFile(file.name)
    }
  }
}

async function processFile(path: string) {
  // Read yaml file
  // Delete a key
  // Write back to file
  const file = await Deno.readTextFile(path)
  const data = yaml.parse(file)

  for (const service in data.services) {
    const definition = data.services[service]
    delete definition.env_file
  }

  const updated = yaml.stringify(data)
  await Deno.writeTextFile(path, updated)
}

// main().catch(console.error)