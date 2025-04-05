import pg from "pg";

import process from "node:process";
import child_process from "node:child_process";

async function resolveApiKey() {
  const { Client } = pg;
  const client = new Client({
    ssl: false,
    connectionString: process.env.DATABASE_URL,
  });
  await client.connect();
  const result = await client.query(
    `
    SELECT
      *
    FROM
      api_keys
  `
  );

  return result.rows[0].api_key;
}

async function startSSEServer(apiKey) {
  const childProcess = child_process.spawn(
    "npx",
    // 'node',
    [
      // 'dist/index.js',
      "-y",
      "@metamcp/mcp-server-metamcp@latest",
      "--metamcp-api-base-url",
      "http://metamcp:3000",
      "--metamcp-api-key",
      apiKey,
      "--transport",
      "sse",
      "--port",
      "12006",
    ],
    {
      stdio: "inherit", // Automatically pipe stdio to parent process
      shell: process.platform === "win32", // Use shell on Windows for command resolution
    }
  );

  // Log process IDs for debugging
  console.log(`Parent process ID: ${process.pid}`);
  console.log(`Child process ID: ${childProcess.pid}`);

  // Handle child process exit
  childProcess.on("exit", (code, signal) => {
    console.log(
      `Child process exited with code ${code} and signal ${signal}`
    );
    // Exit the parent process with the same code
    process.exit(code || 0);
  });

  // Handle child process errors
  childProcess.on("error", (err) => {
    console.error(`Failed to start child process: ${err}`);
    process.exit(1);
  });

  // Forward termination signals to child process
  ["SIGINT", "SIGTERM", "SIGHUP"].forEach((signal) => {
    process.on(signal, () => {
      console.log(`Parent received ${signal}, forwarding to child...`);
      if (!childProcess.killed) {
        childProcess.kill(signal);
      }
    });
  });
}

async function main() {
  const key = await resolveApiKey();
  await startSSEServer(key);
}

main().catch(console.error);
