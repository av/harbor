export type EnvKey = {
  key: string;
  prefix?: string;
}

export type EnvValuePointer = EnvKey & {
  profile?: string;
}

export type EnvValueSetter = EnvValuePointer & {
  value: string;
}

export type EnvJsonValueSetter = EnvValuePointer & {
  value: object;
}

export type ComposeServiceConfig = {
  container_name?: string;
  image?: string;
  volumes?: string[];
  environment?: Record<string, string> | string[];
  ports?: string[];
  networks?: string[];
  [key: string]: unknown;
}

export type ComposeConfig = {
  services?: Record<string, ComposeServiceConfig>;
  networks?: Record<string, unknown>;
  volumes?: Record<string, unknown>;
  [key: string]: unknown;
}

export type ServiceRendererContext = {
  handle: string;
  merged: ComposeConfig;
  serviceConfig: ComposeServiceConfig;
}

export type ServiceRenderer = (ctx: ServiceRendererContext) => Promise<void>;