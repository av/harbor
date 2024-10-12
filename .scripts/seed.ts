import * as toml from 'jsr:@std/toml';
import * as path from 'jsr:@std/path';
import * as collections from "jsr:@std/collections/deep-merge";

const VERSION = "0.2.11";

type ValueSeed = {
  // Path relative to the project root
  target: string;
  value: unknown;
}

// All the values we want to seed
const targets: ValueSeed[] = [{
  target: 'pyproject.toml',
  value: {
    tool: {
      poetry: {
        version: VERSION,
        include: await resolveIncludes(),
      },
    },
  },
}, {
  target: 'package.json',
  value: {
    version: VERSION,
  },
}, {
  target: 'harbor.sh:replace',
  value: {
    'version=".*"': `version="${VERSION}"`,
  },
}, {
  target: 'app/package.json',
  value: {
    version: VERSION,
  },
}, {
  target: 'app/src-tauri/tauri.conf.json',
  value: {
    version: VERSION,
  },
}, {
  target: 'app/src-tauri/Cargo.toml',
  value: {
    package: {
      version: VERSION,
    },
  },
}];

const seeders = {
  '.toml': seedToml,
  '.json': seedJson,
  '.sh:replace': seedReplace,
};

/**
 * Poetry can't configure this out of the box :(
 */
async function resolveIncludes() {
  const command = new Deno.Command('git', {
    args: ['ls-tree', '-r', 'HEAD', '--name-only'],
  });

  const out = await command.output();
  const files = new TextDecoder().decode(out.stdout).split('\n').filter(Boolean);
  return files;
}

async function seedToml(value: ValueSeed) {
  const source = await toml.parse(
    await Deno.readTextFile(value.target)
  );

  const result = collections.deepMerge(source, value.value, { arrays: 'replace' });
  await Deno.writeTextFile(value.target, toml.stringify(result));
}

async function seedJson(value: ValueSeed) {
  const source = JSON.parse(
    await Deno.readTextFile(value.target)
  );

  const result = collections.deepMerge(source, value.value, { arrays: 'replace' });
  await Deno.writeTextFile(value.target, JSON.stringify(result, null, 2));
}

async function seedReplace(value: ValueSeed) {
  const target = value.target.replace(':replace', '');
  const source = await Deno.readTextFile(target);

  let result = source;
  for (const [pattern, replacement] of Object.entries(value.value)) {
    result = result.replace(new RegExp(pattern), replacement);
  }

  await Deno.writeTextFile(target, result);
}

async function seed(value: ValueSeed) {
  const { ext } = path.parse(value.target);

  if (ext in seeders) {
    await seeders[ext as keyof typeof seeders](value);
  }
}

async function main() {
  for (const target of targets) {
    await seed(target);
  }
}

main().catch(console.error);