interface MigrationContext {
  envPath: string;
  dryRun: boolean;
  log: (message: string) => void;
  getEnvValue: (key: string) => Promise<string | undefined>;
  setEnvValue: (key: string, value: string) => Promise<void>;
}

const DEFAULT_DIFY_WORKSPACE = "./dify/volumes";

function isPathLikeSingleValue(value: string): boolean {
  return !value.includes(";") && !value.includes(":");
}

export async function up(context: MigrationContext): Promise<void> {
  // Hermes shipped with an empty API key, which disables auth entirely on
  // an API capable of terminal command execution. Seed the new default for
  // installs that never set a key.
  const hermesKey = await context.getEnvValue("hermes.api_key");

  if (hermesKey === "") {
    if (!context.dryRun) {
      await context.setEnvValue("hermes.api_key", "sk-hermes");
    }
    context.log("seeded hermes.api_key default (was empty / auth disabled)");
  }

  const legacyVolumes = await context.getEnvValue("dify.volumes");

  if (!legacyVolumes) {
    context.log("dify volumes variable already migrated");
    return;
  }

  if (!isPathLikeSingleValue(legacyVolumes)) {
    context.log("dify.volumes contains a custom mount list, leaving as-is");
    return;
  }

  const workspace = await context.getEnvValue("dify.workspace");
  const shouldMoveToWorkspace = !workspace || workspace === DEFAULT_DIFY_WORKSPACE;

  if (!context.dryRun) {
    if (shouldMoveToWorkspace) {
      await context.setEnvValue("dify.workspace", legacyVolumes);
    }

    await context.setEnvValue("dify.volumes", "");
  }

  context.log("migrated dify.volumes path to dify.workspace");
}
