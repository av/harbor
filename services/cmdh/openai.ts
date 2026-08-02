/**
 * This is an override to fix
 * how cmdh interacts with OpenAI-compatible backends.
 *
 * When OPENAI_MODEL_NAME is not set, the model is resolved
 * from the backend's /v1/models list (first entry), so
 * Harbor's OpenAI-mode cross-files work without an explicit model.
 */

import OpenAI from "openai";

async function resolveModel(openai: OpenAI): Promise<string> {
  if (process.env.OPENAI_MODEL_NAME) {
    return process.env.OPENAI_MODEL_NAME;
  }

  const models = await openai.models.list();
  const first = models.data?.[0]?.id;

  if (!first) {
    throw new Error('No models available from the OpenAI-compatible backend and OPENAI_MODEL_NAME is not set.');
  }

  return first;
}

export async function generate(prompt: string, system: string) {
  try {
    const openai = new OpenAI();
    const model = await resolveModel(openai);

    const completion = await openai.chat.completions.create({
      model,
      messages: [
        { role: 'system', content: system },
        { role: 'user', content: prompt }
      ],
      response_format: { type: 'json_object' },
    });

    const content = completion.choices?.[0]?.message?.content;
    if (typeof content === 'string') {
      return content;
    }
    throw new Error('OpenAI response did not contain text content.');
  } catch (e: any) {
    if (e.message?.includes('OPENAI_API_KEY')) {
      console.error('You must set your OpenAI API key using "cmdh configure" before using the OpenAI mode.');
    } else {
      console.error('An error occurred while communicating with the OpenAI API. Please try again later.');
      if (e.message) {
        console.error(`Error message: ${e.message}`)
      }
    }
  }
}
