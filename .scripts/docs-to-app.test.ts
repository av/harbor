/// <reference lib="deno.ns" />

import { createDocsPageSet } from "./docs-links.ts";
import { rewriteMarkdownLinksForApp } from "./docs-to-app.ts";

function assertEquals<T>(actual: T, expected: T) {
  if (actual !== expected) {
    throw new Error(`Expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
  }
}

Deno.test("rewriteMarkdownLinksForApp canonicalizes markdown self-links", () => {
  const docsPages = createDocsPageSet([
    "1.-Harbor-User-Guide.md",
    "2.2.14-Backend&colon-Speaches.md",
    "2.2.18-Backend&colon-STT.md",
  ]);

  const source = [
    "> Harbor also ships [Speaches](./2.2.14-Backend%3A-Speaches.md) — a newer OpenAI-compatible STT/TTS server.",
    "",
    "See Harbor's [environment configuration guide](./1.-Harbor-User-Guide#environment-variables) to set arbitrary environment variables.",
  ].join("\n");

  const expected = [
    "> Harbor also ships [Speaches](./2.2.14-Backend&colon-Speaches.md) — a newer OpenAI-compatible STT/TTS server.",
    "",
    "See Harbor's [environment configuration guide](./1.-Harbor-User-Guide.md#environment-variables) to set arbitrary environment variables.",
  ].join("\n");

  assertEquals(rewriteMarkdownLinksForApp(source, docsPages), expected);
});
