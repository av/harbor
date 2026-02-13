interface MigrationContext {
  envPath: string;
  dryRun: boolean;
  log: (message: string) => void;
  getEnvValue: (key: string) => Promise<string | undefined>;
  setEnvValue: (key: string, value: string) => Promise<void>;
}

const DEFAULT_BASE_IMAGE = "ghcr.io/ggml-org/llama.cpp";

function normalizeBaseImage(value: string): string {
  if (value.endsWith(":server")) {
    return value.slice(0, -":server".length);
  }

  if (value.endsWith(":server-cuda")) {
    return value.slice(0, -":server-cuda".length);
  }

  if (value.endsWith(":server-rocm")) {
    return value.slice(0, -":server-rocm".length);
  }

  return value;
}

export async function up(context: MigrationContext): Promise<void> {
  const hasCpu = (await context.getEnvValue("llamacpp.image.cpu")) !== undefined;
  const hasNvidia = (await context.getEnvValue("llamacpp.image.nvidia")) !== undefined;
  const hasRocm = (await context.getEnvValue("llamacpp.image.rocm")) !== undefined;

  if (hasCpu && hasNvidia && hasRocm) {
    context.log("llamacpp image variables already migrated");
    return;
  }

  const legacyImage = await context.getEnvValue("llamacpp.image");
  const baseImage = normalizeBaseImage(legacyImage || DEFAULT_BASE_IMAGE);

  if (!context.dryRun) {
    await context.setEnvValue("llamacpp.image.cpu", `${baseImage}:server`);
    await context.setEnvValue("llamacpp.image.nvidia", `${baseImage}:server-cuda`);
    await context.setEnvValue("llamacpp.image.rocm", `${baseImage}:server-rocm`);
  }

  context.log("migrated llamacpp image variables");
}
