export interface OllamaModel {
  name: string;
  size: number;
  modified_at: string;
  details?: {
    family?: string;
    parameter_size?: string;
    quantization_level?: string;
    format?: string;
  };
}

export interface HfFileInfo {
  name: string;
  size: number;
}

export interface HfRepoInfo {
  repo: string;
  path: string;
  size: number;
  modified: Date;
  files: HfFileInfo[];
  details: {
    architecture?: string;
    parameters?: string;
    contextLength?: number;
    quantization?: string;
    dtype?: string;
  };
}

export interface ModelEntry {
  source: 'ollama' | 'hf' | 'llamacpp';
  model: string;
  size: number;
  modified: string;
  details: Record<string, string | number | string[]>;
  files?: HfFileInfo[];
}
