import * as oai from './helpers/openaiGeneric.js';
import { qwenNumSeq } from './payloads/ollama.js';

export const options = {
  stages: [
    { duration: '30s', target: 1 },
    { duration: '5m', target: 1 },
    { duration: '30s', target: 0 },
  ]
  // iterations: 20,
};

let requests = 0;
const client = oai.createClient({
  url: 'http://ollama:11434',
  options: {
    model: 'qwen2.5-coder:1.5b-base-q8_0',
  },
});

export default function run() {
  const payload = qwenNumSeq({ size: requests });
  client.chatComplete(payload);
  requests++;
}