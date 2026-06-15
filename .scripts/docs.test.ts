/// <reference lib="deno.ns" />

import {
  clearRootFiles,
  extractManualSections,
  mergeBoostModulesManualSections,
  normalizeSerializedMarkdown,
} from "./docs.ts";

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

Deno.test("extractManualSections pulls agentic overview blocks from 5.2.3", () => {
  const doc = [
    "## cex",
    "",
    "cex body",
    "",
    "## Web search requirement",
    "",
    "manual web search",
    "",
    "## Workspace bind mount",
    "",
    "manual workspace",
    "",
    "## Agentic coding workflow presets",
    "",
    "```mermaid",
    "flowchart TD",
    "    root[\"Which workflow?\"]",
    "```",
    "",
    "## clarity",
    "",
    "clarity body",
    "",
  ].join("\n");

  const sections = extractManualSections(doc);
  assert(sections.length === 3, "expected three manual sections");
  assert(sections[2].includes("Which workflow?"), "expected mermaid decision tree in agentic section");
});

Deno.test("mergeBoostModulesManualSections inserts manual blocks before clarity", () => {
  const generated = "## cex\n\ncex body\n\n## clarity\n\nclarity body\n";
  const manual = [
    "## Web search requirement\n\nmanual web search\n",
    "## Agentic coding workflow presets\n\n```mermaid\nflowchart TD\n```\n",
  ];

  const merged = mergeBoostModulesManualSections(generated, manual);
  const clarityIndex = merged.indexOf("## clarity");
  const webSearchIndex = merged.indexOf("## Web search requirement");
  const agenticIndex = merged.indexOf("## Agentic coding workflow presets");

  assert(webSearchIndex > 0 && agenticIndex > webSearchIndex, "manual sections should precede clarity");
  assert(clarityIndex > agenticIndex, "clarity should follow manual sections");
  assert(!merged.includes("## clarity\n\n## clarity"), "clarity heading should not be duplicated");
});
