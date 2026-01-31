/**
 * This is an override to fix
 * how cmdh interacts with ollama
 */

import { Ollama } from 'ollama';
import { z } from 'zod';
import { zodToJsonSchema } from 'zod-to-json-schema';

const ollama = new Ollama({ host: process.env.OLLAMA_HOST })
const CmdhResponse = z.object({
  assistantMessage: z.string().describe('Additional message for the user'),
  setupCommands: z.array(z.string()).describe('Commands to run before the desired command'),
  desiredCommand: z.string().describe('The command to run'),
  // cmdh throws with any other value
  nonInteractive: z.enum(['true']),
  safetyLevel: z.enum(['delete', 'overwrite', 'safe']).describe('Safety level for the command'),
})

// Generate a response from ollama
export async function generate(prompt, system) {
  const response = await ollama.chat({
    format: zodToJsonSchema(CmdhResponse),
    model: process.env.OLLAMA_MODEL_NAME,
    messages: [{
      'role': 'system',
      'content': system,
    }, {
      'role': 'user',
      'content': prompt
    }],
    stream: true,
    options: {
      num_ctx: 8192,
      temperature: 0,
    },
  });

  let buffer = '';

  for await (const part of response) {
    if (part.message) {
      buffer += part.message.content
    }
  }

  return buffer;
}