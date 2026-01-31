const SPEACHES_URL = process.env.SPEACHES_URL || 'http://speaches:8000';
const TTS_MODEL = process.env.HARBOR_SPEACHES_TTS_MODEL;
const STT_MODEL = process.env.HARBOR_SPEACHES_STT_MODEL;

const STARTUP_RETRIES = 30;
const STARTUP_RETRY_INTERVAL = 500;
const MODEL_RETRIES = 20;
const MODEL_RETRY_INTERVAL = 1000;

async function retryWithBackoff<T>(
  operation: () => Promise<T>,
  checkCondition: (result: T) => boolean,
  options: {
    retries: number;
    interval: number;
    operationName: string;
    successMessage: string;
  }
): Promise<T> {
  console.log(`Harbor: ${options.operationName}...`);
  let retries = options.retries;

  while (retries > 0) {
    try {
      const result = await operation();

      if (checkCondition(result)) {
        console.log(`Harbor: ${options.successMessage}`);
        return result;
      }
    } catch (error) {
      console.error(`Harbor: Error during ${options.operationName.toLowerCase()}:`, error);
    }

    retries--;
    console.log(`Harbor: Retrying in ${options.interval / 1000} seconds... (${retries} retries left)`);
    await new Promise(resolve => setTimeout(resolve, options.interval));
  }

  throw new Error(`Harbor: ${options.operationName} failed after all retries`);
}

async function waitStarted() {
  return retryWithBackoff(
    () => fetch(`${SPEACHES_URL}/health`),
    (response) => response.ok,
    {
      retries: STARTUP_RETRIES,
      interval: STARTUP_RETRY_INTERVAL,
      operationName: 'Waiting for Speaches to start',
      successMessage: 'Speaches is started'
    }
  );
}

async function waitForModel(modelName: string) {
  return retryWithBackoff(
    () => fetch(`${SPEACHES_URL}/v1/models`).then((r) => r.json()),
    (models) => models.data?.some((model: any) => model.id === modelName),
    {
      retries: MODEL_RETRIES,
      interval: MODEL_RETRY_INTERVAL,
      operationName: `Waiting for model ${modelName} to appear in /v1/models`,
      successMessage: `Model ${modelName} is now available`
    }
  );
}

async function setupModel(modelId: string, modelType: string) {
  if (!modelId) return;

  await fetch(`${SPEACHES_URL}/v1/models/${modelId}`, { method: 'POST' });
  await waitForModel(modelId);
}

async function main() {
  await waitStarted();
  await setupModel(TTS_MODEL, 'TTS');
  await setupModel(STT_MODEL, 'STT');
}

main().catch(console.error);