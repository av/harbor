import { IconPlaneLanding, IconRocketLaunch } from "./Icons";

export const ACTION_ICONS = {
    loading: <span className="loading loading-spinner loading-xs"></span>,
    up: <IconRocketLaunch />,
    down: <IconPlaneLanding />,
};

// aka Harbor Service Tag
export enum HST {
    backend = 'Backend',
    frontend = 'Frontend',
    satellite = 'Satellite',
    api = 'API',
    cli = 'CLI',
    partial = 'Partial Support',
    builtIn = 'Built-in',
    eval = 'Eval',
    audio = 'Audio',
};

export const HSTColors: Partial<Record<HST, string>> = {
    [HST.backend]: 'from-primary/10',
    [HST.frontend]: 'from-secondary/10',
    [HST.satellite]: 'from-accent/10',
};

export const HSTColorOpts = Object.keys(HSTColors) as HST[];

export type HarborService = {
    handle: string;
    isRunning: boolean;
    isDefault: boolean;
    tags: HST[] | `${HST}`[];
}

export const serviceMetadata: Record<string, Partial<HarborService>> = {
    aichat: {
        tags: [HST.satellite, HST.cli],
    },
    aider: {
        tags: [HST.satellite, HST.cli],
    },
    airllm: {
        tags: [HST.backend],
    },
    aphrodite: {
        tags: [HST.backend],
    },
    autogpt: {
        tags: [HST.satellite, HST.partial],
    },
    bench: {
        tags: [HST.satellite, HST.cli, HST.builtIn, HST.eval],
    },
    bionicgpt: {
        tags: [HST.frontend],
    },
    boost: {
        tags: [HST.satellite, HST.api, HST.builtIn],
    },
    cfd: {
        tags: [HST.satellite, HST.api, HST.cli],
    },
    chatui: {
        tags: [HST.frontend],
    },
    cmdh: {
        tags: [HST.satellite, HST.cli],
    },
    comfyui: {
        tags: [HST.frontend],
    },
    dify: {
        tags: [HST.satellite],
    },
    fabric: {
        tags: [HST.satellite, HST.cli],
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
    },
    jupyter: {
        tags: [HST.satellite],
    },
    ktransformers: {
        tags: [HST.backend],
    },
    langfuse: {
        tags: [HST.satellite, HST.api],
    },
    librechat: {
        tags: [HST.frontend],
    },
    litellm: {
        tags: [HST.satellite, HST.api],
    },
    llamacpp: {
        tags: [HST.backend],
    },
    lmdeploy: {
        tags: [HST.backend, HST.partial],
    },
    lmeval: {
        tags: [HST.satellite, HST.cli, HST.eval],
    },
    lobechat: {
        tags: [HST.frontend],
    },
    mistralrs: {
        tags: [HST.frontend],
    },
    ol1: {
        tags: [HST.frontend],
    },
    ollama: {
        tags: [HST.backend],
    },
    omnichain: {
        tags: [HST.frontend],
    },
    openhands: {
        tags: [HST.satellite, HST.partial],
    },
    opint: {
        tags: [HST.satellite, HST.cli],
    },
    parler: {
        tags: [HST.backend, HST.audio],
    },
    parllama: {
        tags: [HST.frontend],
    },
    perplexica: {
        tags: [HST.satellite],
    },
    plandex: {
        tags: [HST.satellite, HST.cli],
    },
    qrgen: {
        tags: [HST.satellite, HST.cli],
    },
    searxng: {
        tags: [HST.satellite],
    },
    sglang: {
        tags: [HST.backend],
    },
    stt: {
        tags: [HST.backend, HST.audio],
    },
    tabbyapi: {
        tags: [HST.backend],
    },
    textgrad: {
        tags: [HST.satellite],
    },
    tgi: {
        tags: [HST.backend],
    },
    tts: {
        tags: [HST.backend, HST.audio],
    },
    txtairag: {
        tags: [HST.satellite],
    },
    vllm: {
        tags: [HST.backend],
    },
    webui: {
        tags: [HST.frontend],
    },
    litlytics: {
        tags: [HST.satellite, HST.partial],
    },
    anythingllm: {
        tags: [HST.frontend, HST.partial]
    },
    nexa: {
        tags: [HST.backend, HST.partial],
    },
    repopack: {
        tags: [HST.satellite, HST.cli],
    },
};