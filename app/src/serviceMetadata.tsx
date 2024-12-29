import { IconPlaneLanding, IconRocketLaunch } from "./Icons";
import { HST } from "./ServiceTags";

export const ACTION_ICONS = {
    loading: <span className="loading loading-spinner loading-xs"></span>,
    up: <IconRocketLaunch />,
    down: <IconPlaneLanding />,
};

export type HarborService = {
    handle: string;
    isRunning: boolean;
    isDefault: boolean;
    tags: HST[] | `${HST}`[];
    wikiUrl?: string;
}

export const serviceMetadata: Record<string, Partial<HarborService>> = {
    aichat: {
        tags: [HST.satellite, HST.cli],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.3.14-Satellite:-aichat',
    },
    aider: {
        tags: [HST.satellite, HST.cli],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.3.13-Satellite:-aider',
    },
    airllm: {
        tags: [HST.backend],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.2.11-Backend:-AirLLM',
    },
    aphrodite: {
        tags: [HST.backend],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.2.5-Backend:-Aphrodite-Engine',
    },
    autogpt: {
        tags: [HST.satellite, HST.partial],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.3.15-Satellite:-AutoGPT',
    },
    bench: {
        tags: [HST.satellite, HST.cli, HST.builtIn, HST.eval],
        wikiUrl: 'https://github.com/av/harbor/wiki/5.1.-Harbor-Bench',
    },
    bionicgpt: {
        tags: [HST.frontend],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.1.8-Frontend:-BionicGPT',
    },
    boost: {
        tags: [HST.satellite, HST.api, HST.builtIn],
        wikiUrl: 'https://github.com/av/harbor/wiki/5.2.-Harbor-Boost',
    },
    cfd: {
        tags: [HST.satellite, HST.api, HST.cli],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.3.8-Satellite:-cloudflared',
    },
    chatui: {
        tags: [HST.frontend],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.1.4-Frontend:-ChatUI',
    },
    cmdh: {
        tags: [HST.satellite, HST.cli],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.3.9-Satellite:-cmdh',
    },
    comfyui: {
        tags: [HST.frontend, HST.workflows],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.1.2-Frontend:-ComfyUI',
    },
    dify: {
        tags: [HST.satellite, HST.workflows],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.3.3-Satellite:-Dify',
    },
    fabric: {
        tags: [HST.satellite, HST.cli],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.3.10-Satellite:-fabric',
    },
    gum: {
        tags: [HST.satellite, HST.cli],
    },
    hf: {
        tags: [HST.satellite, HST.cli],
    },
    hfdownloader: {
        tags: [HST.satellite, HST.cli],
    },
    hollama: {
        tags: [HST.frontend],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.1.6-Frontend:-hollama',
    },
    jupyter: {
        tags: [HST.satellite],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.3.18-Satellite:-JupyterLab',
    },
    ktransformers: {
        tags: [HST.backend],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.2.13-Backend:-KTransformers',
    },
    langfuse: {
        tags: [HST.satellite, HST.api],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.3.6-Satellite:-langfuse',
    },
    librechat: {
        tags: [HST.frontend],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.1.3-Frontend:-LibreChat',
    },
    litellm: {
        tags: [HST.satellite, HST.api],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.3.5-Satellite:-LiteLLM',
    },
    llamacpp: {
        tags: [HST.backend],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.2.2-Backend:-llama.cpp',
    },
    lmdeploy: {
        tags: [HST.backend, HST.partial],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.2.10-Backend:-lmdeploy',
    },
    lmeval: {
        tags: [HST.satellite, HST.cli, HST.eval],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.3.17-Satellite:-lm-evaluation-harness',
    },
    lobechat: {
        tags: [HST.frontend],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.1.5-Frontend:-Lobe-Chat',
    },
    mistralrs: {
        tags: [HST.frontend],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.2.6-Backend:-mistral.rs',
    },
    ol1: {
        tags: [HST.frontend],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.3.19-Satellite:-ol1',
    },
    ollama: {
        tags: [HST.backend],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.2.1-Backend:-Ollama',
    },
    omnichain: {
        tags: [HST.frontend],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.3.16-Satellite:-omnichain',
    },
    openhands: {
        tags: [HST.satellite, HST.partial],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.3.20-Satellite:-OpenHands',
    },
    opint: {
        tags: [HST.satellite, HST.cli],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.3.7-Satellite:-Open-Interpreter',
    },
    parler: {
        tags: [HST.backend, HST.audio],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.2.8-Backend:-Parler',
    },
    parllama: {
        tags: [HST.frontend],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.1.7-Frontend:-parllama',
    },
    perplexica: {
        tags: [HST.satellite],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.3.2-Satellite:-Perplexica',
    },
    perplexideez: {
        tags: [HST.satellite, HST.partial],
    },
    plandex: {
        tags: [HST.satellite, HST.cli],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.3.4-Satellite:-Plandex',
    },
    qrgen: {
        tags: [HST.satellite, HST.cli],
    },
    searxng: {
        tags: [HST.satellite],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.3.1-Satellite:-SearXNG',
    },
    sglang: {
        tags: [HST.backend],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.2.12-Backend:-SGLang',
    },
    stt: {
        tags: [HST.backend, HST.audio],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.2.14-Backend:-Faster-Whisper',
    },
    tabbyapi: {
        tags: [HST.backend],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.2.4-Backend:-TabbyAPI',
    },
    textgrad: {
        tags: [HST.satellite],
    },
    tgi: {
        tags: [HST.backend],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.2.9-Backend:-text-generation-inference',
    },
    tts: {
        tags: [HST.backend, HST.audio],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.2.7-Backend:-openedai-speech',
    },
    txtairag: {
        tags: [HST.satellite],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.3.12-Satellite:-TextGrad',
    },
    vllm: {
        tags: [HST.backend],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.2.3-Backend:-vLLM',
    },
    webui: {
        tags: [HST.frontend],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.1.1-Frontend:-Open-WebUI',
    },
    litlytics: {
        tags: [HST.satellite, HST.partial, HST.workflows],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.3.21-Satellite:-LitLytics',
    },
    anythingllm: {
        tags: [HST.frontend, HST.partial],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.1.9-Frontend:-AnythingLLM',
    },
    nexa: {
        tags: [HST.backend, HST.partial],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.2.15-Backend:-Nexa-SDK',
    },
    repopack: {
        tags: [HST.satellite, HST.cli],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.3.22-Satellite:-Repopack',
    },
    n8n: {
        tags: [HST.satellite, HST.workflows],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.3.23-Satellite:-n8n',
    },
    bolt: {
        tags: [HST.satellite],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.3.24-Satellite:-Bolt.new',
    },
    pipelines: {
        tags: [HST.satellite, HST.api, HST.workflows],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.3.25-Satellite:-Open-WebUI-Pipelines',
    },
    chatnio: {
        tags: [HST.frontend],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.1.10-Frontend:-Chat-Nio',
    },
    qdrant: {
        tags: [HST.satellite],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.3.26-Satellite:-Qdrant',
    },
    k6: {
        tags: [HST.satellite, HST.cli],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.3.27-Satellite:-K6',
    },
    promptfoo: {
        tags: [HST.satellite, HST.cli],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.3.28-Satellite:-Promptfoo',
    },
    webtop: {
        tags: [HST.satellite],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.3.29-Satellite:-Webtop',
    },
    omniparser: {
        tags: [HST.satellite],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.3.30-Satellite:-OmniParser',
    },
    flowise: {
        tags: [HST.satellite, HST.workflows],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.3.31-Satellite:-Flowise',
    },
    langflow: {
        tags: [HST.satellite, HST.workflows],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.3.32-Satellite:-LangFlow',
    },
    optillm: {
        tags: [HST.satellite, HST.api],
        wikiUrl: 'https://github.com/av/harbor/wiki/2.3.33-Satellite:-OptiLLM',
    },
};