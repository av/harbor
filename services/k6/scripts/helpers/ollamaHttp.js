import { Trend } from 'k6/metrics';

import config from './config.js';
import * as http from "./http.js";

const url = config.ollama.url;

const ollamaTrends = {
  prompt_tokens: new Trend('ollama_prompt_tokens'),
  completion_tokens: new Trend('ollama_completion_tokens'),
  total_tokens: new Trend('ollama_total_tokens'),
}

export const get = (path, ...args) => http.get(`${url}${path}`, ...args);
export const post = (path, ...args) => {
  // Recognize /v1/chat/completion as a special case
  const isCompletion = path === '/v1/chat/completions';
  const response = http.post(`${url}${path}`, ...args);

  if (isCompletion) {
    const completion = http.getBody(response);

    if (completion.usage) {
      ollamaTrends.prompt_tokens.add(completion.usage.prompt_tokens);
      ollamaTrends.completion_tokens.add(completion.usage.completion_tokens);
      ollamaTrends.total_tokens.add(completion.usage.total_tokens);
    }
  }

  return response;
};
export const graphqlQuery = (...args) => {
  return http.graphql(`${url}/graphql`, ...args);
};
