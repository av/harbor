const markdownExtension = ".md";

type DocsPageResolution = {
  canonicalPath: string;
  anchor: string;
};

type RelativeFileLink = {
  path: string;
  anchor: string;
};

export function createDocsPageSet(fileNames: Iterable<string>): Set<string> {
  return new Set(
    Array.from(fileNames).filter((fileName) => fileName.endsWith(markdownExtension)),
  );
}

export function rewriteLinkForWiki(
  url: string,
  docsPages: ReadonlySet<string>,
  wikiUrl: string,
): string {
  const resolvedPage = resolveDocsPageLink(url, docsPages);
  if (!resolvedPage) {
    return url;
  }

  return `${wikiUrl}/${toWikiPageName(resolvedPage.canonicalPath)}${resolvedPage.anchor}`;
}

export function rewriteLinkForPackageReadme(
  url: string,
  docsPages: ReadonlySet<string>,
): string {
  const resolvedPage = resolveDocsPageLink(url, docsPages);
  if (resolvedPage) {
    return `../docs/${resolvedPage.canonicalPath}${resolvedPage.anchor}`;
  }

  const relativeFile = resolveRelativeFileLink(url);
  if (!relativeFile) {
    return url;
  }

  return `../docs/${relativeFile.path}${relativeFile.anchor}`;
}

export function rewriteLinkForApp(
  url: string,
  docsPages: ReadonlySet<string>,
): string {
  const resolvedPage = resolveDocsPageLink(url, docsPages);
  if (resolvedPage) {
    return `./${resolvedPage.canonicalPath}${resolvedPage.anchor}`;
  }

  const relativeFile = resolveRelativeFileLink(url);
  if (!relativeFile) {
    return url;
  }

  return `./${relativeFile.path}${relativeFile.anchor}`;
}

export function resolveDocsPageLink(
  url: string,
  docsPages: ReadonlySet<string>,
): DocsPageResolution | null {
  const relativeLink = resolveRelativeFileLink(url);
  if (!relativeLink) {
    return null;
  }

  const canonicalPath = resolveCanonicalDocsPagePath(relativeLink.path, docsPages);
  if (!canonicalPath) {
    return null;
  }

  return {
    canonicalPath,
    anchor: relativeLink.anchor,
  };
}

function resolveRelativeFileLink(url: string): RelativeFileLink | null {
  if (!isRelativeUrl(url)) {
    return null;
  }

  const [path, anchor = ""] = url.split(/(#.*)/s, 2);
  const normalizedPath = stripCurrentDirectoryPrefix(path);
  if (!normalizedPath || normalizedPath.startsWith("../")) {
    return null;
  }

  return {
    path: normalizedPath,
    anchor,
  };
}

function resolveCanonicalDocsPagePath(
  path: string,
  docsPages: ReadonlySet<string>,
): string | null {
  return resolveCanonicalDocsPagePathByLookupKey(path, docsPages, toDocsPageLookupKey)
    ?? resolveCanonicalDocsPagePathByLookupKey(path, docsPages, toRelaxedDocsPageLookupKey);
}

function resolveCanonicalDocsPagePathByLookupKey(
  path: string,
  docsPages: ReadonlySet<string>,
  toLookupKey: (path: string) => string,
): string | null {
  const lookupKey = toLookupKey(path);
  let resolvedPath: string | null = null;

  for (const docsPage of docsPages) {
    if (toLookupKey(docsPage) !== lookupKey) {
      continue;
    }

    if (resolvedPath && resolvedPath !== docsPage) {
      return null;
    }

    resolvedPath = docsPage;
  }

  return resolvedPath;
}

function toWikiPageName(path: string): string {
  const pageName = path === "README.md"
    ? "Home"
    : path.slice(0, -markdownExtension.length);

  return normalizeColonEntity(pageName);
}

function normalizeColonEntity(value: string): string {
  return value.replaceAll("&colon;", ":").replaceAll("&colon", ":");
}

function toDocsPageLookupKey(path: string): string {
  const decodedPath = decodePath(path);
  const markdownPath = decodedPath.endsWith(markdownExtension)
    ? decodedPath
    : `${decodedPath}${markdownExtension}`;
  const normalizedPath = normalizeColonEntity(markdownPath)
    .replaceAll(":-", ":");

  return normalizedPath === "Home.md" ? "README.md" : normalizedPath;
}

function toRelaxedDocsPageLookupKey(path: string): string {
  return toDocsPageLookupKey(path).replaceAll(":", "-");
}

function stripCurrentDirectoryPrefix(path: string): string {
  return path.replace(/^\.\//, "");
}

function decodePath(path: string): string {
  try {
    return decodeURIComponent(path);
  } catch {
    return path;
  }
}

function isRelativeUrl(url: string): boolean {
  return !!url && !url.startsWith("#") && !url.startsWith("/") && !hasScheme(url);
}

function hasScheme(url: string): boolean {
  return /^[a-zA-Z][a-zA-Z\d+.-]*:/.test(url);
}
