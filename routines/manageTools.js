import { getJsonValue, setJsonValue, TOOLS_CONFIG_KEY } from "./envManager";
import { CLI_NAME, getArgs, log, nextTick } from "./utils";

export async function manageTools(args) {
  log.debug("Harbor tools routine");

  switch (args[0]) {
    case "import":
    case "i":
    case "add":
      args.shift();
      await importTools(args);
      break;
    case "--help":
    case "-h":
    case "help":
    case "h":
      await nextTick();
      console.log("Manage tools for Harbor and its services");
      console.log(`  ${CLI_NAME} tools <command> [options]`);
      console.log(`    i|import|add <ref> [options] - import tools`);
      process.exit(0);
    default:
      log.error("Invalid command. Use 'merge' or 'list'.");
      process.exit(42);
  }
}

/**
 * @typedef {Object} ToolDefinition
 * @property {string} [ref] - GitHub reference
 * @property {string} [image] - Docker image reference
 * @property {boolean} [mcpo] - Whether this is an MCPO tool
 */

/**
 * @typedef {Record<string, ToolDefinition>} ToolConfig
 */

/**
 * Imports given MCP tools into harbor.
 *
 * Args:
 * --ref <ref> (or the first positional arg) GitHub ref to import
 * --name <name> to specify the tool name (otherwise will derived from the URL)
 *
 * @param {string[]} args
 */
async function importTools(args) {
  const config = await getToolsConfig();

  console.log("===============");
  console.log(config);
  console.log("===============");
  await setToolsConfig(config);
  // await setToolsConfig({
  //   'time': {
  //     'ref': 123,
  //   },
  //   'fetch': {
  //     'image': 'image/fetch:latest',
  //     mcpo: true,
  //   }
  // })
}

/**
 * @returns {Promise<ToolConfig>}
 */
async function getToolsConfig() {
  return getJsonValue({
    key: TOOLS_CONFIG_KEY,
  });
}

/**
 * @param {ToolConfig} config
 * @returns {Promise<void>}
 */
async function setToolsConfig(config) {
  return setJsonValue({
    key: TOOLS_CONFIG_KEY,
    value: config,
  });
}

if (import.meta.main === true) {
  const args = getArgs();
  manageTools(args).catch((err) => log(err));
}
