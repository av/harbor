/**
 * This is an override to fix
 * how cmdh interacts with ollama
 */

import { Ollama } from 'ollama';

const ollama = new Ollama({ host: process.env.OLLAMA_HOST })

// Generate a response from ollama
export async function generate(prompt, system) {
  const response = await ollama.chat({
    temperature: 0,
    model: process.env.OLLAMA_MODEL_NAME,
    format: 'json',
    messages: [{
      'role': 'system',
      'content': system,
    }, {
      'role': 'user',
      'content': prompt
    }],
    stream: true,
  });

  let buffer = '';

  for await (const part of response) {
    if (part.message) {
      buffer += part.message.content
    }
  }
  return buffer;
}