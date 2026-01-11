/**
 * Resolve and write logo URLs to serviceMetadata.ts
 *
 * Usage:
 *   harbor dev add-logos           # Resolve and write logos
 *   harbor dev add-logos --dry-run # Preview without writing
 *
 * Resolution chain:
 * 1. GitHub homepage favicon (if repo has homepage URL)
 * 2. dashboardicons.com (common service icons)
 * 3. GitHub owner avatar
 */

const METADATA_FILE = "./app/src/serviceMetadata.ts";

interface ServiceEntry {
  handle: string;
  name?: string;
  projectUrl?: string;
  logo?: string;
  startLine: number;
  endLine: number;
}

function extractGitHubInfo(url: string): { owner: string; repo: string } | null {
  const match = url.match(/github\.com\/([^\/]+)\/([^\/]+)/);
  if (!match) return null;
  return { owner: match[1], repo: match[2].replace(/\.git$/, '').split('/')[0] };
}

async function checkUrl(url: string): Promise<boolean> {
  try {
    const resp = await fetch(url, { method: 'HEAD', redirect: 'follow' });
    return resp.ok;
  } catch {
    return false;
  }
}

async function getGitHubHomepage(owner: string, repo: string): Promise<string | null> {
  try {
    const resp = await fetch(`https://api.github.com/repos/${owner}/${repo}`, {
      headers: { 'Accept': 'application/vnd.github.v3+json' }
    });
    if (!resp.ok) return null;
    const data = await resp.json();
    return data.homepage || null;
  } catch {
    return null;
  }
}

async function resolveLogo(service: ServiceEntry): Promise<string | null> {
  if (!service.projectUrl) return null;

  const ghInfo = extractGitHubInfo(service.projectUrl);

  // Chain 1: GitHub homepage favicon
  if (ghInfo) {
    const homepage = await getGitHubHomepage(ghInfo.owner, ghInfo.repo);
    if (homepage && !homepage.includes('github.com')) {
      try {
        const domain = new URL(homepage).hostname;
        const faviconUrl = `https://www.google.com/s2/favicons?domain=${domain}&sz=128`;
        if (await checkUrl(faviconUrl)) {
          console.log(`  [favicon] ${service.handle}: ${faviconUrl}`);
          return faviconUrl;
        }
      } catch { /* invalid URL */ }
    }
  }

  // Chain 2: dashboardicons.com
  const iconNames = [
    service.handle,
    service.name?.toLowerCase().replace(/\s+/g, '-'),
    service.name?.toLowerCase().replace(/\s+/g, ''),
  ].filter(Boolean) as string[];

  for (const name of iconNames) {
    const dashUrl = `https://cdn.jsdelivr.net/gh/walkxcode/dashboard-icons/png/${name}.png`;
    if (await checkUrl(dashUrl)) {
      console.log(`  [dashboard] ${service.handle}: ${dashUrl}`);
      return dashUrl;
    }
  }

  // Chain 3: GitHub owner avatar (always works for valid repos)
  if (ghInfo) {
    const avatarUrl = `https://github.com/${ghInfo.owner}.png?size=200`;
    console.log(`  [avatar] ${service.handle}: ${avatarUrl}`);
    return avatarUrl;
  }

  console.log(`  [none] ${service.handle}: no logo found`);
  return null;
}

function parseServices(content: string): ServiceEntry[] {
  const services: ServiceEntry[] = [];
  const lines = content.split('\n');

  let inMetadata = false;
  let currentHandle: string | null = null;
  let currentService: Partial<ServiceEntry> = {};
  let braceDepth = 0;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    if (line.includes('serviceMetadata:')) {
      inMetadata = true;
      continue;
    }

    if (!inMetadata) continue;

    // Match service entry start: "    handle: {"
    const handleMatch = line.match(/^\s{4}(\w[\w-]*)\s*:\s*\{/);
    if (handleMatch && braceDepth === 0) {
      currentHandle = handleMatch[1];
      braceDepth = 1;
      currentService = { handle: currentHandle, startLine: i };
      continue;
    }

    if (currentHandle) {
      braceDepth += (line.match(/\{/g) || []).length;
      braceDepth -= (line.match(/\}/g) || []).length;

      // Extract fields
      const nameMatch = line.match(/name:\s*['"]([^'"]+)['"]/);
      if (nameMatch) currentService.name = nameMatch[1];

      const urlMatch = line.match(/projectUrl:\s*['"]([^'"]+)['"]/);
      if (urlMatch) currentService.projectUrl = urlMatch[1];

      const logoMatch = line.match(/logo:\s*['"]([^'"]+)['"]/);
      if (logoMatch) currentService.logo = logoMatch[1];

      if (braceDepth === 0) {
        currentService.endLine = i;
        services.push(currentService as ServiceEntry);
        currentHandle = null;
        currentService = {};
      }
    }
  }

  return services;
}

function insertLogo(content: string, service: ServiceEntry, logoUrl: string): string {
  const lines = content.split('\n');

  // Find the line with projectUrl in this service's range
  for (let i = service.startLine; i <= service.endLine; i++) {
    if (lines[i].includes('projectUrl:')) {
      const indent = lines[i].match(/^(\s*)/)?.[1] || '        ';
      lines.splice(i + 1, 0, `${indent}logo: '${logoUrl}',`);
      break;
    }
  }

  return lines.join('\n');
}

async function main() {
  const dryRun = Deno.args.includes('--dry-run');

  console.log(`Resolving logos${dryRun ? ' (dry-run)' : ''}...\n`);

  let content = await Deno.readTextFile(METADATA_FILE);
  const services = parseServices(content);

  const withoutLogo = services.filter(s => !s.logo && s.projectUrl);
  const withLogo = services.filter(s => s.logo);

  console.log(`Total: ${services.length} | With logo: ${withLogo.length} | To resolve: ${withoutLogo.length}\n`);

  let resolved = 0;
  const updates: Array<{ service: ServiceEntry; logo: string }> = [];

  for (const service of withoutLogo) {
    const logo = await resolveLogo(service);
    if (logo) {
      updates.push({ service, logo });
      resolved++;
    }
  }

  if (!dryRun && updates.length > 0) {
    // Apply updates in reverse order to preserve line numbers
    updates.reverse();
    for (const { service, logo } of updates) {
      content = insertLogo(content, service, logo);
    }
    await Deno.writeTextFile(METADATA_FILE, content);
    console.log(`\nWrote ${resolved} logos to ${METADATA_FILE}`);
  } else if (dryRun) {
    console.log(`\nDry run: would write ${resolved} logos`);
  } else {
    console.log(`\nNo new logos to write`);
  }
}

main().catch(console.error);
