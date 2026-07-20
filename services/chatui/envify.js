// Custom script similar to the one from original repo:
// https://github.com/huggingface/chat-ui/blob/main/scripts/updateLocalEnv.ts

// Transforms the .yml env vars into a .env.local file
// .yml is used to merge configs of multiple services together

import fs from "fs";
import yaml from "js-yaml";

const file = fs.readFileSync("/app/final.yaml", "utf8");
const prod = JSON.parse(JSON.stringify(yaml.load(file)));
const vars = prod.envVars;

let localEnv = "";

Object.entries(vars).forEach(([key, value]) => {
  // Models needs to be a JSON string
  if (key === 'MODELS') {
    value = JSON.stringify(value);
  }

	localEnv += `${key}=\`${value}\`\n`;
});

// chat-ui >= 0.10 replaced the MODELS list with a single OpenAI-compatible
// provider configured via OPENAI_BASE_URL / OPENAI_API_KEY (models are
// discovered from its /models endpoint). Bridge the legacy Harbor MODELS
// config to the new scheme using the first configured endpoint so the
// per-backend configs (chatui.llamacpp.yml etc.) keep working.
const firstEndpoint = vars.MODELS?.[0]?.endpoints?.find((e) => e.type === "openai");

if (firstEndpoint && !vars.OPENAI_BASE_URL) {
  localEnv += `OPENAI_BASE_URL=\`${firstEndpoint.baseURL}\`\n`;
  localEnv += `OPENAI_API_KEY=\`${firstEndpoint.apiKey ?? "sk-chatui"}\`\n`;
}

// Write full_config to .env.local
fs.writeFileSync(".env.local", localEnv);