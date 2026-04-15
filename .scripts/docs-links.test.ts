/// <reference lib="deno.ns" />

import {
  createDocsPageSet,
  rewriteLinkForApp,
  rewriteLinkForPackageReadme,
  rewriteLinkForWiki,
} from "./docs-links.ts";

function assertEquals<T>(actual: T, expected: T) {
  if (actual !== expected) {
    throw new Error(`Expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
  }
}

const wikiUrl = "https://github.com/av/harbor/wiki";
const docsPages = createDocsPageSet([
  "README.md",
  "3.-Harbor-CLI-Reference.md",
  "1.1-Harbor-App.md",
  "4.-Compatibility.md",
  "8.-Harbor-Troubleshooting.md",
  "2.1.1-Frontend&colon-Open-WebUI.md",
  "2.2.1-Backend&colon-Ollama.md",
  "2.3.29-Satellite&colon-Webtop.md",
  "2.3.33-Satellite&colon-OptiLLM.md",
  "2.3.4-Satellite&colon-Plandex.md",
  "2.3.41-Satellite-libretranslate.md",
  "2.3.42-Satellite-metamcp.md",
]);

Deno.test("rewriteLinkForWiki strips .md and preserves anchors", () => {
  assertEquals(
    rewriteLinkForWiki("./3.-Harbor-CLI-Reference.md#harbor-config", docsPages, wikiUrl),
    "https://github.com/av/harbor/wiki/3.-Harbor-CLI-Reference#harbor-config",
  );
});

Deno.test("rewriteLinkForWiki normalizes repo and encoded colon page names", () => {
  assertEquals(
    rewriteLinkForWiki("./2.1.1-Frontend&colon-Open-WebUI.md#setup", docsPages, wikiUrl),
    "https://github.com/av/harbor/wiki/2.1.1-Frontend:-Open-WebUI#setup",
  );
  assertEquals(
    rewriteLinkForWiki("./2.1.1-Frontend%3A-Open-WebUI.md#setup", docsPages, wikiUrl),
    "https://github.com/av/harbor/wiki/2.1.1-Frontend:-Open-WebUI#setup",
  );
  assertEquals(
    rewriteLinkForWiki("./2.2.1-Backend%3AOllama.md#setup", docsPages, wikiUrl),
    "https://github.com/av/harbor/wiki/2.2.1-Backend:-Ollama#setup",
  );
  assertEquals(
    rewriteLinkForWiki("./2.3.29-Satellite-Webtop.md", docsPages, wikiUrl),
    "https://github.com/av/harbor/wiki/2.3.29-Satellite:-Webtop",
  );
});

Deno.test("rewriteLinkForWiki maps README to Home", () => {
  assertEquals(
    rewriteLinkForWiki("./README.md#intro", docsPages, wikiUrl),
    "https://github.com/av/harbor/wiki/Home#intro",
  );
});

Deno.test("rewriteLinkForWiki rewrites reported canonical .md page targets", () => {
  assertEquals(
    rewriteLinkForWiki("./8.-Harbor-Troubleshooting.md", docsPages, wikiUrl),
    "https://github.com/av/harbor/wiki/8.-Harbor-Troubleshooting",
  );
  assertEquals(
    rewriteLinkForWiki("./Compatibility.md#ollama---truncated-input", docsPages, wikiUrl),
    "./Compatibility.md#ollama---truncated-input",
  );
  assertEquals(
    rewriteLinkForWiki("./4.-Compatibility.md#ollama---truncated-input", docsPages, wikiUrl),
    "https://github.com/av/harbor/wiki/4.-Compatibility#ollama---truncated-input",
  );
  assertEquals(
    rewriteLinkForWiki("./2.3.41-Satellite-libretranslate.md", docsPages, wikiUrl),
    "https://github.com/av/harbor/wiki/2.3.41-Satellite-libretranslate",
  );
  assertEquals(
    rewriteLinkForWiki("./2.3.42-Satellite-metamcp.md", docsPages, wikiUrl),
    "https://github.com/av/harbor/wiki/2.3.42-Satellite-metamcp",
  );
  assertEquals(
    rewriteLinkForWiki("./2.3.4-Satellite&colon-Plandex.md", docsPages, wikiUrl),
    "https://github.com/av/harbor/wiki/2.3.4-Satellite:-Plandex",
  );
});

Deno.test("rewriteLinkForPackageReadme canonicalizes docs page links", () => {
  assertEquals(
    rewriteLinkForPackageReadme("3.-Harbor-CLI-Reference#harbor-config", docsPages),
    "../docs/3.-Harbor-CLI-Reference.md#harbor-config",
  );
  assertEquals(
    rewriteLinkForPackageReadme("./2.1.1-Frontend%3A-Open-WebUI.md#setup", docsPages),
    "../docs/2.1.1-Frontend&colon-Open-WebUI.md#setup",
  );
  assertEquals(
    rewriteLinkForPackageReadme("./2.2.1-Backend%3AOllama.md#setup", docsPages),
    "../docs/2.2.1-Backend&colon-Ollama.md#setup",
  );
  assertEquals(
    rewriteLinkForPackageReadme("./Home#intro", docsPages),
    "../docs/README.md#intro",
  );
  assertEquals(
    rewriteLinkForPackageReadme("./2.3.29-Satellite-Webtop.md", docsPages),
    "../docs/2.3.29-Satellite&colon-Webtop.md",
  );
  assertEquals(
    rewriteLinkForPackageReadme("./8.-Harbor-Troubleshooting.md", docsPages),
    "../docs/8.-Harbor-Troubleshooting.md",
  );
  assertEquals(
    rewriteLinkForPackageReadme("./2.3.33-Satellite&colon-OptiLLM", docsPages),
    "../docs/2.3.33-Satellite&colon-OptiLLM.md",
  );
});

Deno.test("rewriteLinkForPackageReadme keeps relative files as files", () => {
  assertEquals(
    rewriteLinkForPackageReadme("./langflow.png", docsPages),
    "../docs/langflow.png",
  );
  assertEquals(
    rewriteLinkForPackageReadme("./not-a-doc.md#section", docsPages),
    "../docs/not-a-doc.md#section",
  );
});

Deno.test("rewriteLinkForApp canonicalizes docs page links", () => {
  assertEquals(
    rewriteLinkForApp("3.-Harbor-CLI-Reference#harbor-config", docsPages),
    "./3.-Harbor-CLI-Reference.md#harbor-config",
  );
  assertEquals(
    rewriteLinkForApp("./2.1.1-Frontend%3A-Open-WebUI.md#setup", docsPages),
    "./2.1.1-Frontend&colon-Open-WebUI.md#setup",
  );
  assertEquals(
    rewriteLinkForApp("./2.2.1-Backend%3AOllama.md#setup", docsPages),
    "./2.2.1-Backend&colon-Ollama.md#setup",
  );
  assertEquals(
    rewriteLinkForApp("./Home#intro", docsPages),
    "./README.md#intro",
  );
  assertEquals(
    rewriteLinkForApp("./2.3.29-Satellite-Webtop.md", docsPages),
    "./2.3.29-Satellite&colon-Webtop.md",
  );
});

Deno.test("rewriteLinkForApp keeps relative files as files", () => {
  assertEquals(
    rewriteLinkForApp("./langflow.png", docsPages),
    "./langflow.png",
  );
  assertEquals(
    rewriteLinkForApp("./not-a-doc.md#section", docsPages),
    "./not-a-doc.md#section",
  );
});
