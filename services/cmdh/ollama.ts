/**
 * This is an override to fix
 * how cmdh interacts with ollama
 */

import { Ollama } from 'ollama';

const ollama = new Ollama({ host: process.env.OLLAMA_HOST })
// Literal JSON schema: zod-to-json-schema v3 silently emits an empty schema
// when paired with zod v4, which Ollama rejects ("invalid JSON schema in format")
const CmdhResponseSchema = {
  type: 'object',
  properties: {
    assistantMessage: { type: 'string', description: 'Additional message for the user' },
    setupCommands: {
      type: 'array',
      items: { type: 'string' },
      description: 'Commands to run before the desired command',
    },
    desiredCommand: { type: 'string', description: 'The command to run' },
    // cmdh throws with any other value
    nonInteractive: { type: 'string', enum: ['true'] },
    safetyLevel: {
      type: 'string',
      enum: ['delete', 'overwrite', 'safe'],
      description: 'Safety level for the command',
    },
  },
  required: ['assistantMessage', 'setupCommands', 'desiredCommand', 'nonInteractive', 'safetyLevel'],
  additionalProperties: false,
}

// Generate a response from ollama
export async function generate(prompt, system) {
  const response = await ollama.chat({
    format: CmdhResponseSchema,
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