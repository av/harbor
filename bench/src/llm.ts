import { config } from "./config.ts";
import { omit, sleep } from './utils.ts';
import { log } from './log.ts';
import { prompts } from './judge.ts';

export type LLMOptions = {
  max_tokens?: number;
  temperature?: number;
}

export type LLMConfig = {
  model: string;
  apiUrl: string;
  apiKey?: string;
  prompt?: keyof typeof prompts;
  options?: LLMOptions;
};

export class LLM {
  llm: LLMConfig;

  constructor(llm: LLMConfig) {
    this.llm = llm;
  }

  async chat(message: string, options = {}): Promise<string> {
    const maxRetries = 4;
    let retries = 0;

    while (retries < maxRetries) {
      try {
        return await this.attemptChat(message, options);
      } catch (error) {
        retries++;
        if (retries >= maxRetries) {
          throw error;
        }
        log(`Attempt ${retries} failed. Retrying in ${2 ** retries} seconds...`);
        await sleep(2 ** retries * 1000); // Exponential backoff
      }
    }

    throw new Error('Max retries reached');
  }

  private async attemptChat(message: string, options = {}): Promise<string> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json'
    };

    if (this.llm.apiKey) {
      headers['Authorization'] = `Bearer ${this.llm.apiKey}`;
    }

    if (config.debug) {
      log(`>> ${message}`);
    }

    const body = JSON.stringify({
      ...this.completionOptions,
      model: this.llm.model,
      messages: [
        {
          role: 'user',
          content: message,
        }
      ],
      stream: false,
    });

    const response = await fetch(`${this.llm.apiUrl}/v1/chat/completions`, {
      method: 'POST',
      headers,
      body
    });

    if (!response.ok) {
      const text = await response.text();
      log(`Failed to fetch completion: ${text}`);
      throw new Error(`Failed to fetch completion: ${response.statusText}`);
    }

    const data = await response.json();
    const reply = data.choices[0].message.content.trim();

    if (config.debug) {
      console.debug(`<< ${reply}`);
    }

    return reply;
  }

  toJson() {
    return omit({
      ...this.llm,
      ...this.completionOptions,
    }, ['apiKey']);
  }

  get completionOptions() {
    const system = [
      'model',
      'apiUrl',
      'apiKey',
      'prompt',
      'options',
    ];

    const draft = {
      ...(this.llm?.options || {}),
      ...omit(this.llm, system),
    };

    if ('max_tokens' in draft) {
      draft.max_tokens = parseInt(draft.max_tokens as any);
    }

    if ('temperature' in draft) {
      draft.temperature = parseFloat(draft.temperature as any);
    }

    if ('seed' in draft) {
      draft.seed = parseInt(draft.seed as any);
    }

    return draft;
  }
}