/// <reference lib="deno.ns" />
import process from 'node:process';
import { getArgs, consumeFlagArg, log } from './utils';
import { listOllamaModels, removeOllamaModel } from './models/ollama';
import { listHfModels, removeHfModel } from './models/hf';
import { listLlamacppModels, removeLlamacppModel } from './models/llamacpp';
import { formatTable, formatJson } from './models/format';
import type { ModelEntry } from './models/types';

async function cmdList(args: string[]) {
  const jsonMode = consumeFlagArg(args, ['--json', '-j']);

  const [ollamaModels, hfRepos, llamacppModels] = await Promise.all([
    listOllamaModels(),
    listHfModels(),
    listLlamacppModels(),
  ]);

  const entries: ModelEntry[] = [
    ...ollamaModels.map(m => ({
      source: 'ollama' as const,
      model: m.name,
      size: m.size,
      modified: m.modified_at,
      details: {
        ...(m.details?.family && { family: m.details.family }),
        ...(m.details?.parameter_size && { parameters: m.details.parameter_size }),
        ...(m.details?.quantization_level && { quantization: m.details.quantization_level }),
      },
    })),
    ...hfRepos.map(r => ({
      source: 'hf' as const,
      model: r.repo,
      size: r.size,
      modified: r.modified.toISOString(),
      details: r.details as Record<string, string | number | string[]>,
      files: r.files,
    })),
    ...llamacppModels,
  ];

  if (jsonMode) {
    process.stdout.write(formatJson(entries) + '\n');
  } else {
    process.stdout.write(formatTable(entries) + '\n');
  }
}

async function cmdRemove(args: string[]) {
  const modelSpec = args[0];
  if (!modelSpec) {
    log.error('Usage: harbor models rm <model>');
    process.exit(1);
  }

  let removedAny = false;

  const ollamaModels = await listOllamaModels();
  const ollamaMatch = ollamaModels.find(
    m => m.name === modelSpec || m.name.startsWith(modelSpec + ':')
  );
  if (ollamaMatch) {
    const removed = await removeOllamaModel(ollamaMatch.name);
    if (removed) {
      log.info(`Removed from Ollama: ${ollamaMatch.name}`);
      removedAny = true;
    }
  }

  const hfRemoved = await removeHfModel(modelSpec);
  if (hfRemoved) {
    log.info(`Removed from HuggingFace cache: ${modelSpec}`);
    removedAny = true;
  }

  const llamacppRemoved = await removeLlamacppModel(modelSpec);
  if (llamacppRemoved) {
    log.info(`Removed from llamacpp cache: ${modelSpec}`);
    removedAny = true;
  }

  if (!removedAny) {
    log.error(`Model not found in Ollama, HuggingFace, or llamacpp cache: ${modelSpec}`);
    process.exit(1);
  }
}

async function main(args: string[]) {
  const cmd = args[0];
  args = args.slice(1);

  switch (cmd) {
    case 'ls':
    case 'list':
      await cmdList(args);
      break;
    case 'rm':
    case 'remove':
      await cmdRemove(args);
      break;
    default:
      log.error(`Unknown command: ${cmd}. Use ls or rm.`);
      process.exit(1);
  }
}

if (import.meta.main === true) {
  const args = getArgs();
  main(args).catch(err => { log(err); process.exit(1); });
}
