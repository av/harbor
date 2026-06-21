interface MigrationContext {
  envPath: string;
  dryRun: boolean;
  log: (message: string) => void;
  getEnvValue: (key: string) => Promise<string | undefined>;
  setEnvValue: (key: string, value: string) => Promise<void>;
}

export async function up(context: MigrationContext): Promise<void> {
  const volumes = await context.getEnvValue("dify.volumes");

  if (!volumes) {
    context.log("dify.volumes already cleared");
    return;
  }

  if (!context.dryRun) {
    await context.setEnvValue("dify.volumes", "");
  }

  context.log("cleared dify.volumes");
}
