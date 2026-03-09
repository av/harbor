/// <reference lib="deno.worker" />

// @ts-ignore npm specifier
import { gguf, parseGGUFQuantLabel } from 'npm:@huggingface/gguf';

self.onmessage = async (e: MessageEvent<{ filePath: string; filename: string; id: number }>) => {
  const { filePath, filename, id } = e.data;
  try {
    const { metadata } = await gguf(filePath, { allowLocalFile: true });
    const md = metadata as Record<string, unknown>;
    const arch = (md['general.architecture'] as string | undefined) || undefined;
    const parameters = (md['general.size_label'] as string | undefined) || undefined;
    const fileType = md['general.file_type'];
    const quantization = fileType != null ? String(fileType) : parseGGUFQuantLabel(filename) ?? undefined;
    const contextLength = arch && md[`${arch}.context_length`] != null
      ? Number(md[`${arch}.context_length`])
      : undefined;
    self.postMessage({ id, result: { architecture: arch, parameters, quantization, contextLength } });
  } catch {
    self.postMessage({ id, result: { quantization: parseGGUFQuantLabel(filename) ?? undefined } });
  }
};
