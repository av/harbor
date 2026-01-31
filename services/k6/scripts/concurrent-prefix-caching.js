import { randomSeed } from 'k6';

import * as oai from './helpers/openaiGeneric.js';
import { any } from './helpers/utils.js';
import { fimCompletion } from './payloads/completions.js';

const prefixes = [
  '//',
  '#',
  '/*',
  'def',
  'class',
  'function',
  '--',
  'import',
]

const config = {
  prefix: any(prefixes),

  // vllm
  // client: {
  //   http: oai.createClient({
  //     url: 'http://vllm:8000',
  //   }),
  //   extra: {
  //     // Default
  //     model: 'Qwen/Qwen2.5-Coder-1.5B',
  //     // GPTQ Int 8
  //     // model: 'Qwen/Qwen2.5-Coder-1.5B-Instruct-GPTQ-Int8'
  //     // AWQ
  //     // model: 'Qwen/Qwen2.5-Coder-1.5B-Instruct-AWQ'
  //   },
  // },

  // ollama
  client: {
    http: oai.createClient({
      url: 'http://ollama:11434',
    }),
    extra: {
      // FIM fix doesn't work with OpenAI-compatible API
      model: 'qwen2.5-coder:1.5b-base-q8_0',
    },
  },
}

export const options = {
  stages: [
    // Base
    // { duration: '30s', target: 10 },
    // { duration: '3m', target: 10 },
    // { duration: '30s', target: 0 },

    // Stress-test
    // { duration: '5m', target: 100 },

    // Solo user latency
    { duration: '5m', target: 1 },
  ],
};

let counter = 0;

// This script is to verify code completion performance
// between Ollama and vLLM on the FIM task.
//
// We take starting prefix and then generate a
// fixed iterations of completions recursively
export default function run() {
  randomSeed(counter++);

  const payload = fimCompletion({
    prefix: config.prefix,
    max_tokens: 16,
    ...config.client.extra,
  });
  const response = config.client.http.complete(payload);
  const content = oai.getContent(response);

  config.prefix += content;

  if (content === '') {
    config.prefix = any(prefixes);
  }

  // console.log(config.prefix)
}