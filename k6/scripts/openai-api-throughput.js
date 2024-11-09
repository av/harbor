import { randomSeed } from 'k6';

import * as oai from './helpers/openaiGeneric.js';
import { any, sequenceScenarios } from './helpers/utils.js';
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
  // Should be an array of OpenAI-compatible clients
  clients: [
    oai.createClient({
      url: 'http://ollama:11434',
      options: {
        model: 'qwen2.5-coder:1.5b-base-q8_0',
      },
    }),

    // oai.createClient({
    //   url: 'http://vllm:8000',
    //   options: {
    //     model: 'Qwen/Qwen2.5-Coder-1.5B-Instruct-AWQ',
    //   }
    // }),
  ],
}

// In seconds
const duration = 60;

const scenario = (i, vus) => ({
  [`client_${i}_${vus}vu`]: {
    executor: 'constant-vus',
    vus,
    env: { clientIndex: i.toString() }
  }
})

// For every client - run a few stages
// with various concurrency
export const options = {
  scenarios: sequenceScenarios({
    ...config.clients.reduce((scenarios, _, i) => ({
      ...scenarios,
      ...scenario(i, 1),
      ...scenario(i, 2),
      ...scenario(i, 5),
      ...scenario(i, 10),
    }), {})
  }, duration)
};

let counter = 0;
export default function run() {
  randomSeed(counter++);

  const clientIndex = __ENV.clientIndex;
  const client = config.clients[clientIndex];
  const payload = fimCompletion({
    prefix: config.prefix,
    max_tokens: 64,
  });

  const response = client.complete(payload);
  const content = oai.getContent(response);

  config.prefix += content;
  if (content === '') {
    config.prefix = any(prefixes);
  }
}