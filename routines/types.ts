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