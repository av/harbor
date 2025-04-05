
/**
 * ⚠️ It's important for this file to stay compatible with Deno
 * as it's used for the document generation.
 */

// aka Harbor Service Tag
export enum HST {
    backend = "Backend",
    frontend = "Frontend",
    satellite = "Satellite",
    api = "API",
    cli = "CLI",
    partial = "Partial Support",
    builtIn = "Built-in",
    eval = "Eval",
    audio = "Audio",
    workflows = "Workflows",
    tools = "Tools",
}

export type HarborService = {
    name?: string;
    handle: string;
    isRunning: boolean;
    isDefault: boolean;
    tags: HST[] | `${HST}`[];
    wikiUrl?: string;
    tooltip?: string;
}

export const wikiUrl = 'https://github.com/av/harbor/wiki';

export const serviceMetadata: Record<string, Partial<HarborService>> = {
    aichat: {
        name: 'aichat',
        tags: [HST.satellite, HST.cli],
        wikiUrl: `${wikiUrl}/2.3.14-Satellite:-aichat`,
        tooltip: 'All-in-one LLM CLI tool featuring Shell Assistant, Chat-REPL, RAG, AI tools & agents.',
    },
    aider: {
        name: 'Aider',
        tags: [HST.satellite, HST.cli],
        wikiUrl: `${wikiUrl}/2.3.13-Satellite:-aider`,
        tooltip: 'Aider is AI pair programming in your terminal.',
    },
    airllm: {
        name: 'AirLLM',
        tags: [HST.backend],
        wikiUrl: `${wikiUrl}/2.2.11-Backend:-AirLLM`,
        tooltip: '70B inference with single 4GB GPU (very slow, though)',
    },
    aphrodite: {
        name: 'Aphrodite',
        tags: [HST.backend],
        wikiUrl: `${wikiUrl}/2.2.5-Backend:-Aphrodite-Engine`,
        tooltip: 'Large-scale LLM inference engine',
    },
    autogpt: {
        name: 'autogpt',
        tags: [HST.satellite, HST.partial],
        wikiUrl: `${wikiUrl}/2.3.15-Satellite:-AutoGPT`,
        tooltip: 'Create, deploy, and manage continuous AI agents that automate complex workflows.',
    },
    bench: {
        name: 'Harbor Bench',
        tags: [HST.satellite, HST.cli, HST.builtIn, HST.eval],
        wikiUrl: `${wikiUrl}/5.1.-Harbor-Bench`,
        tooltip: 'Harbor\'s own tool to evaluate LLMs and inference backends against custom tasks.',
    },
    bionicgpt: {
        name: 'BionicGPT',
        tags: [HST.frontend],
        wikiUrl: `${wikiUrl}/2.1.8-Frontend:-BionicGPT`,
        tooltip: 'on-premise LLM web UI with support for OpenAI-compatible backends',
    },
    boost: {
        name: 'Harbor Boost',
        tags: [HST.satellite, HST.api, HST.builtIn],
        wikiUrl: `${wikiUrl}/5.2.-Harbor-Boost`,
        tooltip: 'Connects to downstream LLM API and serves a wrapper with custom workflow. For example, it can be used to add a CoT (Chain of Thought) to an existing LLM API, and much more. Scriptable with Python.',
    },
    cfd: {
        name: 'cloudflared',
        tags: [HST.satellite, HST.api, HST.cli],
        wikiUrl: `${wikiUrl}/2.3.8-Satellite:-cloudflared`,
        tooltip: 'A helper service allowing to expose Harbor services over the internet.',
    },
    chatui: {
        name: 'HuggingFace ChatUI',
        tags: [HST.frontend],
        wikiUrl: `${wikiUrl}/2.1.4-Frontend:-ChatUI`,
        tooltip: 'A chat interface using open source models, eg OpenAssistant or Llama. It is a SvelteKit app and it powers the HuggingChat app on hf.co/chat.',
    },
    cmdh: {
        name: 'cmdh',
        tags: [HST.satellite, HST.cli],
        wikiUrl: `${wikiUrl}/2.3.9-Satellite:-cmdh`,
        tooltip: 'Create Linux commands from natural language, in the shell.',
    },
    comfyui: {
        name: 'ComfyUI',
        tags: [HST.frontend, HST.workflows],
        wikiUrl: `${wikiUrl}/2.1.2-Frontend:-ComfyUI`,
        tooltip: 'The most powerful and modular diffusion model GUI, api and backend with a graph/nodes interface.',
    },
    dify: {
        name: 'Dify',
        tags: [HST.satellite, HST.workflows],
        wikiUrl: `${wikiUrl}/2.3.3-Satellite:-Dify`,
        tooltip: 'An open-source LLM app development platform.',
    },
    fabric: {
        name: 'Fabric',
        tags: [HST.satellite, HST.cli],
        wikiUrl: `${wikiUrl}/2.3.10-Satellite:-fabric`,
        tooltip: 'LLM-driven processing of the text data in the terminal.',
    },
    gum: {
        name: 'Gum',
        tags: [HST.satellite, HST.cli],
    },
    hf: {
        name: 'HuggingFace CLI',
        tags: [HST.satellite, HST.cli],
    },
    hfdownloader: {
        name: 'HuggingFace Downloader',
        tags: [HST.satellite, HST.cli],
    },
    hollama: {
        name: 'Hollama',
        tags: [HST.frontend],
        wikiUrl: `${wikiUrl}/2.1.6-Frontend:-hollama`,
        tooltip: 'A minimal web-UI for talking to Ollama servers.',
    },
    jupyter: {
        name: 'JupyterLab',
        tags: [HST.satellite],
        wikiUrl: `${wikiUrl}/2.3.18-Satellite:-JupyterLab`,
        tooltip: 'Helper service to author/run Jupyter notebooks in Python with access to Harbor services.',
    },
    ktransformers: {
        name: 'KTransformers',
        tags: [HST.backend],
        wikiUrl: `${wikiUrl}/2.2.13-Backend:-KTransformers`,
        tooltip: 'A Flexible Framework for Experiencing Cutting-edge LLM Inference Optimizations',
    },
    langfuse: {
        name: 'LangFuse',
        tags: [HST.satellite, HST.api],
        wikiUrl: `${wikiUrl}/2.3.6-Satellite:-langfuse`,
        tooltip: 'Open source LLM engineering platform: LLM Observability, metrics, evals, prompt management, playground, datasets.',
    },
    librechat: {
        name: 'LibreChat',
        tags: [HST.frontend],
        wikiUrl: `${wikiUrl}/2.1.3-Frontend:-LibreChat`,
        tooltip: 'Open-source ChatGPT UI alternative supporting multiple AI providers (Anthropic, AWS, OpenAI, Azure, Groq, Mistral, Google) with features like model switching, message search, and multi-user support. Includes integration with DALL-E-3 and various APIs.',
    },
    litellm: {
        name: 'LiteLLM',
        tags: [HST.satellite, HST.api],
        wikiUrl: `${wikiUrl}/2.3.5-Satellite:-LiteLLM`,
        tooltip: 'LLM proxy that can aggregate multiple inference APIs together into a single endpoint.',
    },
    llamacpp: {
        name: 'llama.cpp',
        tags: [HST.backend],
        wikiUrl: `${wikiUrl}/2.2.2-Backend:-llama.cpp`,
        tooltip: 'LLM inference in C/C++',
    },
    lmdeploy: {
        name: 'lmdeploy',
        tags: [HST.backend, HST.partial],
        wikiUrl: `${wikiUrl}/2.2.10-Backend:-lmdeploy`,
        tooltip: '',
    },
    lmeval: {
        name: 'lm-evaluation-harness',
        tags: [HST.satellite, HST.cli, HST.eval],
        wikiUrl: `${wikiUrl}/2.3.17-Satellite:-lm-evaluation-harness`,
        tooltip: 'A de-facto standard framework for the few-shot evaluation of language models.',
    },
    lobechat: {
        name: 'Lobe Chat',
        tags: [HST.frontend],
        wikiUrl: `${wikiUrl}/2.1.5-Frontend:-Lobe-Chat`,
        tooltip: 'An open-source, modern-design AI chat framework. Supports Multi AI Providers( OpenAI / Claude 3 / Gemini / Ollama / Azure / DeepSeek), Knowledge Base (file upload / knowledge management / RAG ), Multi-Modals (Vision/TTS) and plugin system.',
    },
    mistralrs: {
        name: 'mistral.rs',
        tags: [HST.frontend],
        wikiUrl: `${wikiUrl}/2.2.6-Backend:-mistral.rs`,
        tooltip: 'Blazingly fast LLM inference.',
    },
    ol1: {
        name: 'ol1',
        tags: [HST.frontend],
        wikiUrl: `${wikiUrl}/2.3.19-Satellite:-ol1`,
        tooltip: 'A simple Gradio app implementing an o1-like chain of reasoning with Ollama.',
    },
    ollama: {
        name: 'Ollama',
        tags: [HST.backend],
        wikiUrl: `${wikiUrl}/2.2.1-Backend:-Ollama`,
        tooltip: 'Get up and running with Llama 3.2, Mistral, Gemma 3, and other large language models.',
    },
    omnichain: {
        name: 'Omnichain',
        tags: [HST.frontend],
        wikiUrl: `${wikiUrl}/2.3.16-Satellite:-omnichain`,
        tooltip: 'Visual programming for AI language models',
    },
    openhands: {
        name: 'OpenHands',
        tags: [HST.satellite, HST.partial],
        wikiUrl: `${wikiUrl}/2.3.20-Satellite:-OpenHands`,
        tooltip: 'A platform for software development agents powered by AI.',
    },
    opint: {
        name: 'Open Interpreter',
        tags: [HST.satellite, HST.cli],
        wikiUrl: `${wikiUrl}/2.3.7-Satellite:-Open-Interpreter`,
        tooltip: 'A natural language interface for computers.',
    },
    parler: {
        name: 'Parler',
        tags: [HST.backend, HST.audio],
        wikiUrl: `${wikiUrl}/2.2.8-Backend:-Parler`,
        tooltip: 'Inference and training library for high-quality TTS models.',
    },
    parllama: {
        name: 'Parllama',
        tags: [HST.frontend],
        wikiUrl: `${wikiUrl}/2.1.7-Frontend:-parllama`,
        tooltip: 'TUI for Ollama',
    },
    perplexica: {
        name: 'Perplexica',
        tags: [HST.satellite],
        wikiUrl: `${wikiUrl}/2.3.2-Satellite:-Perplexica`,
        tooltip: 'An AI-powered search engine. It is an Open source alternative to Perplexity AI.',
    },
    perplexideez: {
        name: 'perplexideez',
        tags: [HST.satellite, HST.partial],
    },
    plandex: {
        name: 'Plandex',
        tags: [HST.satellite, HST.cli],
        wikiUrl: `${wikiUrl}/2.3.4-Satellite:-Plandex`,
        tooltip: 'AI driven development in your terminal.',
    },
    qrgen: {
        name: 'QR Code Generator',
        tags: [HST.satellite, HST.cli],
    },
    searxng: {
        name: 'SearXNG',
        tags: [HST.satellite],
        wikiUrl: `${wikiUrl}/2.3.1-Satellite:-SearXNG`,
        tooltip: 'A privacy-respecting, hackable metasearch engine. Highly configurable and can be used for Web RAG use-cases.',
    },
    sglang: {
        name: 'SGLang',
        tags: [HST.backend],
        wikiUrl: `${wikiUrl}/2.2.12-Backend:-SGLang`,
        tooltip: 'SGLang is a fast serving framework for large language models and vision language models.',
    },
    stt: {
        name: 'faster-whisper-server',
        tags: [HST.backend, HST.audio, HST.partial],
        wikiUrl: `${wikiUrl}/2.2.14-Backend:-Speaches`,
        tooltip: 'Legacy version of Speaches, use that instead.',
    },
    speaches: {
        name: 'Speaches',
        tags: [HST.backend, HST.audio],
        wikiUrl: `${wikiUrl}/2.2.14-Backend:-Speaches`,
        tooltip: 'an OpenAI API-compatible speech server (formerly `faster-whisper-server`), both TTS and STT',
    },
    tabbyapi: {
        name: 'TabbyAPI',
        tags: [HST.backend],
        wikiUrl: `${wikiUrl}/2.2.4-Backend:-TabbyAPI`,
        tooltip: 'An OAI compatible exllamav2 API that\'s both lightweight and fast',
    },
    textgrad: {
        name: 'TextGrad',
        tags: [HST.satellite],
        wikiUrl: `${wikiUrl}/2.3.12-Satellite:-TextGrad`,
        tooltip: 'Automatic "Differentiation" via Text - using large language models to backpropagate textual gradients.',
    },
    tgi: {
        name: 'Text Generation Inference',
        tags: [HST.backend],
        wikiUrl: `${wikiUrl}/2.2.9-Backend:-text-generation-inference`,
        tooltip: 'Inference engine from HuggingFace.',
    },
    tts: {
        name: 'openedai-speech',
        tags: [HST.backend, HST.audio],
        wikiUrl: `${wikiUrl}/2.2.7-Backend:-openedai-speech`,
        tooltip: 'An OpenAI API compatible text to speech server using Coqui AI\'s xtts_v2 and/or piper tts as the backend.',
    },
    txtairag: {
        name: 'txtai RAG',
        tags: [HST.satellite],
        wikiUrl: `${wikiUrl}/2.3.11-Satellite:-txtai-RAG`,
        tooltip: 'RAG WebUI built with txtai.',
    },
    vllm: {
        name: 'vLLM',
        tags: [HST.backend],
        wikiUrl: `${wikiUrl}/2.2.3-Backend:-vLLM`,
        tooltip: 'A high-throughput and memory-efficient inference and serving engine for LLMs',
    },
    webui: {
        name: 'Open WebUI',
        tags: [HST.frontend],
        wikiUrl: `${wikiUrl}/2.1.1-Frontend:-Open-WebUI`,
        tooltip: 'widely adopted and feature rich web interface for interacting with LLMs. Supports OpenAI-compatible and Ollama backends, multi-users, multi-model chats, custom prompts, TTS, Web RAG, RAG, and much much more.',
    },
    litlytics: {
        name: 'LitLytics',
        tags: [HST.satellite, HST.partial, HST.workflows],
        wikiUrl: `${wikiUrl}/2.3.21-Satellite:-LitLytics`,
        tooltip: 'Simple analytics platform that leverages LLMs to automate data analysis.',
    },
    anythingllm: {
        name: 'AnythingLLM',
        tags: [HST.frontend, HST.partial],
        wikiUrl: `${wikiUrl}/2.1.9-Frontend:-AnythingLLM`,
        tooltip: 'The all-in-one Desktop & Docker AI application with built-in RAG, AI agents, and more.',
    },
    nexa: {
        name: 'Nexa SDK',
        tags: [HST.backend, HST.partial],
        wikiUrl: `${wikiUrl}/2.2.15-Backend:-Nexa-SDK`,
        tooltip: 'Nexa SDK is a comprehensive toolkit for supporting ONNX and GGML models.',
    },
    repopack: {
        name: 'Repopack',
        tags: [HST.satellite, HST.cli],
        wikiUrl: `${wikiUrl}/2.3.22-Satellite:-Repopack`,
        tooltip: 'A powerful tool that packs your entire repository into a single, AI-friendly file.',
    },
    n8n: {
        name: 'n8n',
        tags: [HST.satellite, HST.workflows],
        wikiUrl: `${wikiUrl}/2.3.23-Satellite:-n8n`,
        tooltip: 'Fair-code workflow automation platform with native AI capabilities.',
    },
    bolt: {
        name: 'Bolt.new',
        tags: [HST.satellite],
        wikiUrl: `${wikiUrl}/2.3.24-Satellite:-Bolt.new`,
        tooltip: 'Prompt, run, edit, and deploy full-stack web applications.',
    },
    pipelines: {
        name: 'Open WebUI Pipelines',
        tags: [HST.satellite, HST.api, HST.workflows],
        wikiUrl: `${wikiUrl}/2.3.25-Satellite:-Open-WebUI-Pipelines`,
        tooltip: 'UI-Agnostic OpenAI API Plugin Framework.',
    },
    chatnio: {
        name: 'Chat Nio',
        tags: [HST.frontend],
        wikiUrl: `${wikiUrl}/2.1.10-Frontend:-Chat-Nio`,
        tooltip: 'Comprehensive LLM web interface with built-in marketplace',
    },
    qdrant: {
        name: 'Qdrant',
        tags: [HST.satellite],
        wikiUrl: `${wikiUrl}/2.3.26-Satellite:-Qdrant`,
        tooltip: 'Qdrant - High-performance, massive-scale Vector Database and Vector Search Engine.',
    },
    k6: {
        name: 'K6',
        tags: [HST.satellite, HST.cli],
        wikiUrl: `${wikiUrl}/2.3.27-Satellite:-K6`,
        tooltip: 'A modern load testing tool, using Go and JavaScript - https://k6.io',
    },
    promptfoo: {
        name: 'Promptfoo',
        tags: [HST.satellite, HST.cli],
        wikiUrl: `${wikiUrl}/2.3.28-Satellite:-Promptfoo`,
        tooltip: 'Test your prompts, agents, and RAGs. A developer-friendly local tool for testing LLM applications.',
    },
    webtop: {
        name: 'Webtop',
        tags: [HST.satellite],
        wikiUrl: `${wikiUrl}/2.3.29-Satellite:-Webtop`,
        tooltip: 'Linux in a web browser supporting popular desktop environments.',
    },
    omniparser: {
        name: 'OmniParser',
        tags: [HST.satellite],
        wikiUrl: `${wikiUrl}/2.3.30-Satellite:-OmniParser`,
        tooltip: 'A simple screen parsing tool towards pure vision based GUI agent.',
    },
    flowise: {
        name: 'Flowise',
        tags: [HST.satellite, HST.workflows],
        wikiUrl: `${wikiUrl}/2.3.31-Satellite:-Flowise`,
        tooltip: 'Drag & drop UI to build your customized LLM flow.',
    },
    langflow: {
        name: 'LangFlow',
        tags: [HST.satellite, HST.workflows],
        wikiUrl: `${wikiUrl}/2.3.32-Satellite:-LangFlow`,
        tooltip: 'A low-code app builder for RAG and multi-agent AI applications.',
    },
    optillm: {
        name: 'OptiLLM',
        tags: [HST.satellite, HST.api],
        wikiUrl: `${wikiUrl}/2.3.33-Satellite:-OptiLLM`,
        tooltip: 'Optimising LLM proxy that implements many advanced workflows to boost the performance of the LLMs.',
    },
    kobold: {
        name: 'KoboldCpp',
        tags: [HST.satellite, HST.frontend, HST.backend],
        wikiUrl: `${wikiUrl}/2.2.16-Backend:-KoboldCpp`,
        tooltip: 'KoboldCpp is an easy-to-use AI text-generation software for GGML and GGUF models.',
    },
    agent: {
        name: 'Agent',
        tags: [HST.builtIn, HST.cli],
        wikiUrl: ''
    },
    morphic: {
        name: 'Morphic',
        tags: [HST.satellite],
        wikiUrl: `${wikiUrl}/2.3.34-Satellite-Morphic`,
        tooltip: 'An AI-powered search engine with a generative UI, similar to Perplexity and Perplexica.',
    },
    sqlchat: {
        name: 'SQL Chat',
        tags: [HST.satellite],
        wikiUrl: `${wikiUrl}/2.3.35-Satellite-SQL-Chat`,
        tooltip: 'Chat-based SQL client, which uses natural language to communicate with the database.',
    },
    gptme: {
        name: 'gptme',
        tags: [HST.satellite, HST.cli],
        wikiUrl: `${wikiUrl}/2.3.36-Satellite-gptme`,
        tooltip: 'A simple CLI tool to interact with LLMs.',
    },
    mikupad: {
        name: 'Mikupad',
        tags: [HST.frontend],
        wikiUrl: `${wikiUrl}/2.1.11-Frontend:-Mikupad`,
        tooltip: 'LLM Frontend in a single HMTL file',
    },
    traefik: {
        name: 'Traefik',
        tags: [HST.satellite, HST.api],
        wikiUrl: `${wikiUrl}/2.3.37-Satellite-traefik`,
        tooltip: 'A modern HTTP reverse proxy and load balancer that makes deploying microservices easy.',
    },
    latentscope: {
        name: 'Latent Scope',
        tags: [HST.satellite],
        wikiUrl: `${wikiUrl}/2.3.38-Satellite-Latent-Scope`,
        tooltip: 'A new kind of workflow + tool for visualizing and exploring datasets through the lens of latent spaces.',
    },
    oterm: {
        name: 'oterm',
        tags: [HST.frontend, HST.cli],
        wikiUrl: `${wikiUrl}/2.1.12-Frontend-oterm`,
        tooltip: 'The text-based terminal client for Ollama.',
    },
    raglite: {
        name: 'RAGLite',
        tags: [HST.satellite],
        wikiUrl: `${wikiUrl}/2.3.39-Satellite-RAGLite`,
        tooltip: 'Python toolkit for Retrieval-Augmented Generation (RAG)',
    },
    llamaswap: {
        name: 'llama-swap',
        tags: [HST.satellite, HST.api],
        wikiUrl: `${wikiUrl}/2.3.40-Satellite-llamaswap`,
        tooltip: 'Runs multiple llama.cpp servers on demand for seamless switching between them.',
    },
    libretranslate: {
        name: 'LibreTranslate',
        tags: [HST.satellite],
        wikiUrl: `${wikiUrl}/2.3.41-Satellite-LibreTranslate`,
        tooltip: 'A free and open-source machine translation.',
    },
    metamcp: {
        name: 'MetaMCP',
        tags: [HST.satellite, HST.tools],
        wikiUrl: `${wikiUrl}/2.3.42-Satellite-MetaMCP`,
        tooltip: 'Allows to manage MCPs via a WebUI, exposes multiple MCPs as a single server.'
    },
    mcpo: {
        name: 'mcpo',
        tags: [HST.satellite, HST.tools],
        wikiUrl: `${wikiUrl}/2.3.43-Satellite-mcpo`,
        tooltip: 'Turn MCP servers into OpenAPI REST APIs - use them anywhere.',
    },
    'mcp-inspector': {
        name: 'MCP Inspector',
        tags: [HST.satellite, HST.cli, HST.tools],
    },
    'supergateway': {
        name: 'SuperGateway',
        tags: [HST.satellite, HST.cli, HST.tools],
        wikiUrl: `${wikiUrl}/2.3.44-Satellite-supergateway`,
        tooltip: 'A simple and powerful API gateway for LLMs.',
    }
};
