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

// Write full_config to .env.local
fs.writeFileSync(".env.local", localEnv);