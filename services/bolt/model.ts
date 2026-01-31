import { createOpenAI } from '@ai-sdk/openai';

export function getModel() {
  return createOpenAI({
    name: 'Ollama',
    apiKey: 'sk-ollama',
    baseURL: 'http://localhost:33821',
  })
}