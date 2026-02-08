import { Trend } from 'k6/metrics';

import * as http from "./http.js";

const openaiTrends = {
  prompt_tokens: new Trend('prompt_tokens'),
  completion_tokens: new Trend('completion_tokens'),
  total_tokens: new Trend('total_tokens'),
  tokens_per_second: new Trend('tokens_per_second'),
}

const completionEndpoints = new Set([
  '/v1/chat/completions',
  '/v1/completions',
])

export const createClient = (config) => {
  const {
    url,
    options,
  } = config;
  const clientGet = (path, ...args) => http.get(`${url}${path}`, ...args);
  const clientPost = (path, ...args) => {
    const response = http.post(`${url}${path}`, ...args);

    // These should return token stats
    if (completionEndpoints.has(path)) {
      const completion = http.getBody(response);

      if (completion.usage) {
        openaiTrends.prompt_tokens.add(completion.usage.prompt_tokens);
        openaiTrends.completion_tokens.add(completion.usage.completion_tokens);
        openaiTrends.total_tokens.add(completion.usage.total_tokens);

        const durationSeconds = (response.timings.duration - response.timings.sending) / 1000;
        const tokensPerSecond = completion.usage.completion_tokens / durationSeconds;
        openaiTrends.tokens_per_second.add(tokensPerSecond);
      }
    }

    return response;
  };

  const complete = (body, ...args) => {
    return clientPost('/v1/completions', { ...body, ...options }, ...args);
  };

  const chatComplete = (body, ...args) => {
    return clientPost('/v1/chat/completions', { ...body, ...options}, ...args);
  }

  return {
    config,
    get: clientGet,
    post: clientPost,
    complete,
    chatComplete,
  };
}

export const getContent = (response) => {
  const body = http.getBody(response);

  // Generic completion
  if (body.choices) {
    return body.choices[0].text;
  }

  // Chat completion
  if (body.choices) {
    return body.choices[0].message;
  }

  throw new Error(`OpenAIGeneric: Unknown response format: ${response.body}`);
}