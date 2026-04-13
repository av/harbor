const SHARDED_GGUF_RE = /-(\d+)-of-(\d+)\.gguf$/i;

export interface GgufShardInfo {
  logicalName: string;
  logicalStem: string;
  shardIndex?: number;
  shardCount?: number;
}

export function parseGgufShardInfo(filename: string): GgufShardInfo {
  const match = filename.match(SHARDED_GGUF_RE);
  const logicalName = match ? filename.replace(SHARDED_GGUF_RE, '.gguf') : filename;

  return {
    logicalName,
    logicalStem: logicalName.replace(/\.gguf$/i, ''),
    ...(match && {
      shardIndex: Number(match[1]),
      shardCount: Number(match[2]),
    }),
  };
}

export function compareGgufShardNames(a: string, b: string): number {
  const aInfo = parseGgufShardInfo(a);
  const bInfo = parseGgufShardInfo(b);

  if (aInfo.logicalName !== bInfo.logicalName) {
    return aInfo.logicalName.localeCompare(bInfo.logicalName);
  }

  if (aInfo.shardIndex != null && bInfo.shardIndex != null) {
    return aInfo.shardIndex - bInfo.shardIndex;
  }

  if (aInfo.shardIndex != null) return -1;
  if (bInfo.shardIndex != null) return 1;
  return a.localeCompare(b);
}