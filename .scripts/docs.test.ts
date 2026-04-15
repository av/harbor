/// <reference lib="deno.ns" />

import { clearRootFiles } from "./docs.ts";
import { normalizeSerializedMarkdown } from "./docs.ts";

function assert(condition: unknown, message: string) {
  if (!condition) {
    throw new Error(message);
  }
}

Deno.test({
  name: "clearRootFiles removes stale wiki files but preserves directories",
  async fn() {
  const tempDir = await Deno.makeTempDir();

  try {
    await Deno.writeTextFile(`${tempDir}/stale.md`, "stale");
    await Deno.mkdir(`${tempDir}/.git`);
    await Deno.writeTextFile(`${tempDir}/.git/config`, "repo");

    await clearRootFiles(tempDir);

    await Deno.stat(`${tempDir}/.git`);

    let staleExists = true;
    try {
      await Deno.stat(`${tempDir}/stale.md`);
    } catch (error) {
      if (error instanceof Deno.errors.NotFound) {
        staleExists = false;
      } else {
        throw error;
      }
    }

    assert(!staleExists, "expected stale root file to be removed");
  } finally {
    await Deno.remove(tempDir, { recursive: true });
  }
  },
});

Deno.test("normalizeSerializedMarkdown preserves docs entity paths", () => {
  const source = "- [`optillm`](../docs/2.3.33-Satellite\\&colon-OptiLLM.md) as a backend\n";
  const expected = "- [`optillm`](../docs/2.3.33-Satellite&colon-OptiLLM.md) as a backend\n";

  assert(normalizeSerializedMarkdown(source) === expected, "expected escaped &colon entity to be unescaped in markdown links");
});
