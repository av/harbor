/// <reference lib="deno.ns" />
import process from 'node:process';
import { getArgs, consumeArg, consumeFlagArg, log } from './utils';
import { listOllamaModels, removeOllamaModel } from './models/ollama';
import { listHfModels, removeHfModel } from './models/hf';
import { listLlamacppModels, removeLlamacppModel } from './models/llamacpp';
import { listOpenAiCompatibleModels } from './models/openai';
import { formatTable, formatJson } from './models/format';
import type { ModelEntry } from './models/types';

const MODEL_SOURCES: ModelEntry['source'][] = ['ollama', 'hf', 'llamacpp', 'dmr', 'mlx', 'omlx'];

function validateSource(source: ModelEntry['source'] | undefined): void {
  if (!source) return;
  if (!MODEL_SOURCES.includes(source)) {
    log.error(`Unknown model source: ${source}. Expected one of: ${MODEL_SOURCES.join(', ')}`);
    process.exit(1);
  }
}

async function cmdList(args: string[]) {
  const jsonMode = consumeFlagArg(args, ['--json', '-j']);
  const source = consumeArg(args, ['--source', '-s']) as ModelEntry['source'] | undefined;
  validateSource(source);

  const shouldList = (name: ModelEntry['source']) => !source || source === name;

  const [ollamaModels, hfRepos, llamacppModels, dmrModels, mlxModels, omlxModels] = await Promise.all([
    shouldList('ollama') ? listOllamaModels() : Promise.resolve([]),
    shouldList('hf') ? listHfModels() : Promise.resolve([]),
    shouldList('llamacpp') ? listLlamacppModels() : Promise.resolve([]),
    shouldList('dmr') ? listOpenAiCompatibleModels({ source: 'dmr', url: process.env.HARBOR_DMR_URL, apiKey: process.env.HARBOR_DMR_API_KEY }) : Promise.resolve([]),
    shouldList('mlx') ? listOpenAiCompatibleModels({ source: 'mlx', url: process.env.HARBOR_MLX_URL }) : Promise.resolve([]),
    shouldList('omlx') ? listOpenAiCompatibleModels({ source: 'omlx', url: process.env.HARBOR_OMLX_URL, apiKey: process.env.HARBOR_OMLX_API_KEY }) : Promise.resolve([]),
  ]);

  const entries: ModelEntry[] = [
    ...(shouldList('ollama') ? ollamaModels.map(m => ({
      source: 'ollama' as const,
      model: m.name,
      size: m.size,
      modified: m.modified_at,
      details: {
        ...(m.details?.family && { family: m.details.family }),
        ...(m.details?.parameter_size && { parameters: m.details.parameter_size }),
        ...(m.details?.quantization_level && { quantization: m.details.quantization_level }),
      },
    })) : []),
    ...(shouldList('hf') ? hfRepos.map(r => ({
      source: 'hf' as const,
      model: r.repo,
      size: r.size,
      modified: r.modified.toISOString(),
      details: r.details as Record<string, string | number | string[]>,
      files: r.files,
    })) : []),
    ...(shouldList('llamacpp') ? llamacppModels : []),
    ...dmrModels,
    ...mlxModels,
    ...omlxModels,
  ];

  if (jsonMode) {
    process.stdout.write(formatJson(entries) + '\n');
  } else {
    process.stdout.write(formatTable(entries) + '\n');
  }
}

async function cmdRemove(args: string[]) {
  const source = consumeArg(args, ['--source', '-s']) as ModelEntry['source'] | undefined;
  validateSource(source);
  const modelSpec = args[0];
  if (!modelSpec) {
    log.error('Usage: harbor models rm <model>');
    process.exit(1);
  }

  let removedAny = false;

  if (!source || source === 'ollama') {
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
  }

  if (!source || source === 'hf') {
    const hfRemoved = await removeHfModel(modelSpec);
    if (hfRemoved) {
      log.info(`Removed from HuggingFace cache: ${modelSpec}`);
      removedAny = true;
    }
  }

  if (!source || source === 'llamacpp') {
    const llamacppRemoved = await removeLlamacppModel(modelSpec);
    if (llamacppRemoved) {
      log.info(`Removed from llamacpp cache: ${modelSpec}`);
      removedAny = true;
    }
  }

  if (!removedAny) {
    const location = source ? `${source}` : 'Ollama, HuggingFace, or llamacpp cache';
    log.error(`Model not found in ${location}: ${modelSpec}`);
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
