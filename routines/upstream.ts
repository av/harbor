import * as yaml from "jsr:@std/yaml";
import { paths } from "./paths";
import { log } from "./utils";

export interface UpstreamConfig {
  source: string;
  prefix: string;
  include?: string[];
  exclude?: string[];
  init?: {
    image: string;
    script: string;
    volumes?: string[];
  };
}

export interface HarborConfig {
  upstream?: UpstreamConfig;
  metadata?: {
    tags?: string[];
    wikiUrl?: string;
  };
  configs?: {
    base?: string;
    cross?: Record<string, string>;
  };
}

export interface ComposeFile {
  services?: Record<string, ServiceDefinition>;
  volumes?: Record<string, unknown>;
  networks?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface ServiceDefinition {
  container_name?: string;
  depends_on?: string[] | Record<string, { condition?: string }>;
  networks?: string[] | Record<string, unknown>;
  network_mode?: string;
  volumes?: string[];
  [key: string]: unknown;
}

/**
 * Load and parse a harbor.yaml configuration file
 */
export async function loadHarborConfig(servicePath: string): Promise<HarborConfig | null> {
  const configPath = `${servicePath}/harbor.yaml`;
  try {
    const content = await Deno.readTextFile(configPath);
    return yaml.parse(content) as HarborConfig;
  } catch {
    return null;
  }
}

/**
 * Load upstream config from harbor.yaml (for backward compatibility)
 */
export async function loadUpstreamConfig(servicePath: string): Promise<UpstreamConfig | null> {
  const config = await loadHarborConfig(servicePath);
  return config?.upstream || null;
}

/**
 * Check if a service directory has a harbor.yaml configuration
 */
export async function hasHarborConfig(serviceName: string): Promise<boolean> {
  const servicePath = `${paths.home}/${serviceName}`;
  const config = await loadHarborConfig(servicePath);
  return config !== null;
}

/**
 * Check if a service directory has an upstream configuration
 */
export async function hasUpstreamConfig(serviceName: string): Promise<boolean> {
  const servicePath = `${paths.home}/${serviceName}`;
  const config = await loadUpstreamConfig(servicePath);
  return config !== null;
}

/**
 * Transform a stock compose file according to upstream config rules
 */
export function transformUpstreamCompose(
  compose: ComposeFile,
  config: UpstreamConfig,
  servicePath: string
): ComposeFile {
  const { prefix, include, exclude } = config;
  const transformed: ComposeFile = {
    services: {},
    volumes: {},
    networks: {
      "harbor-network": { external: true },
    },
  };

  // Build set of service names to include
  const serviceNames = Object.keys(compose.services || {});
  const includedServices = new Set<string>();

  for (const name of serviceNames) {
    if (include && include.length > 0) {
      if (include.includes(name)) {
        includedServices.add(name);
      }
    } else if (exclude && exclude.length > 0) {
      if (!exclude.includes(name)) {
        includedServices.add(name);
      }
    } else {
      includedServices.add(name);
    }
  }

  // Transform services
  for (const [name, service] of Object.entries(compose.services || {})) {
    if (!includedServices.has(name)) {
      continue;
    }

    const newName = `${prefix}-${name}`;
    const transformedService = transformService(
      service,
      name,
      prefix,
      includedServices,
      servicePath
    );
    transformed.services![newName] = transformedService;
  }

  // Transform volumes (prefix them to avoid conflicts)
  for (const [name, volumeConfig] of Object.entries(compose.volumes || {})) {
    const newName = `${prefix}-${name}`;
    transformed.volumes![newName] = volumeConfig;
  }

  // Copy over any x- extension fields (YAML anchors are already resolved)
  for (const [key, value] of Object.entries(compose)) {
    if (key.startsWith("x-")) {
      transformed[key] = value;
    }
  }

  // Add init container if configured
  if (config.init) {
    transformed.services![`${prefix}-init`] = createInitContainer(config, prefix, servicePath);
    
    // Make all other services depend on init
    for (const [name, service] of Object.entries(transformed.services!)) {
      if (name !== `${prefix}-init`) {
        addInitDependency(service as ServiceDefinition, `${prefix}-init`);
      }
    }
  }

  return transformed;
}

/**
 * Transform a single service definition
 */
function transformService(
  service: ServiceDefinition,
  originalName: string,
  prefix: string,
  includedServices: Set<string>,
  servicePath: string
): ServiceDefinition {
  const transformed: ServiceDefinition = { ...service };

  // Set container name with harbor prefix
  transformed.container_name = `\${HARBOR_CONTAINER_PREFIX}.${prefix}-${originalName}`;

  // Add harbor-network to networks
  if (Array.isArray(transformed.networks)) {
    if (!transformed.networks.includes("harbor-network")) {
      transformed.networks = [...transformed.networks, "harbor-network"];
    }
  } else if (typeof transformed.networks === "object" && transformed.networks !== null) {
    transformed.networks = {
      ...transformed.networks,
      "harbor-network": {},
    };
  } else if (!transformed.network_mode) {
    // Only add network if not using network_mode
    transformed.networks = ["harbor-network"];
  }

  // Transform depends_on references
  if (transformed.depends_on) {
    transformed.depends_on = transformDependsOn(
      transformed.depends_on,
      prefix,
      includedServices
    );
  }

  // Transform network_mode: service:X references
  if (transformed.network_mode?.startsWith("service:")) {
    const referencedService = transformed.network_mode.replace("service:", "");
    if (includedServices.has(referencedService)) {
      transformed.network_mode = `service:${prefix}-${referencedService}`;
    }
  }

  // Transform volume references to use prefixed named volumes
  if (transformed.volumes) {
    transformed.volumes = transformVolumes(transformed.volumes, prefix, servicePath);
  }

  // Add env_file for harbor integration
  const envFiles = ["./.env", `./${servicePath.split("/").pop()}/override.env`];
  if (Array.isArray(transformed.env_file)) {
    transformed.env_file = [...envFiles, ...transformed.env_file];
  } else if (transformed.env_file) {
    transformed.env_file = [...envFiles, transformed.env_file];
  } else {
    transformed.env_file = envFiles;
  }

  return transformed;
}

/**
 * Transform depends_on to use prefixed service names
 */
function transformDependsOn(
  dependsOn: string[] | Record<string, { condition?: string }>,
  prefix: string,
  includedServices: Set<string>
): string[] | Record<string, { condition?: string }> {
  if (Array.isArray(dependsOn)) {
    return dependsOn.map((dep) =>
      includedServices.has(dep) ? `${prefix}-${dep}` : dep
    );
  }

  const transformed: Record<string, { condition?: string }> = {};
  for (const [dep, config] of Object.entries(dependsOn)) {
    const newDep = includedServices.has(dep) ? `${prefix}-${dep}` : dep;
    transformed[newDep] = config;
  }
  return transformed;
}

/**
 * Transform volume mounts to use prefixed named volumes
 */
function transformVolumes(
  volumes: string[],
  prefix: string,
  servicePath: string
): string[] {
  return volumes.map((vol) => {
    // Named volume format: "volumename:/path" or "volumename:/path:ro"
    // Bind mount format: "./path:/path" or "/absolute/path:/path"
    const parts = vol.split(":");
    if (parts.length >= 2) {
      const source = parts[0];
      // Check if it's a named volume (not starting with . or /)
      if (!source.startsWith(".") && !source.startsWith("/")) {
        parts[0] = `${prefix}-${source}`;
        return parts.join(":");
      }
      // Relative paths need to be adjusted to service directory
      if (source.startsWith("./")) {
        // Stock compose paths are relative to upstream dir
        // We need to make them relative to harbor root
        const serviceDir = servicePath.split("/").pop();
        const upstreamRelative = source.slice(2); // Remove "./"
        parts[0] = `./${serviceDir}/upstream/${upstreamRelative}`;
        return parts.join(":");
      }
    }
    return vol;
  });
}

/**
 * Create an init container service definition
 */
function createInitContainer(
  config: UpstreamConfig,
  prefix: string,
  servicePath: string
): ServiceDefinition {
  const serviceDir = servicePath.split("/").pop();
  const init: ServiceDefinition = {
    image: config.init!.image,
    container_name: `\${HARBOR_CONTAINER_PREFIX}.${prefix}-init`,
    command: ["sh", `-c`, `sh /scripts/init.sh`],
    volumes: [
      `./${serviceDir}/${config.init!.script}:/scripts/init.sh:ro`,
      ...(config.init!.volumes || []).map((v) =>
        v.replace("{prefix}", prefix)
      ),
    ],
    networks: ["harbor-network"],
    restart: "no",
  };
  return init;
}

/**
 * Add init container dependency to a service
 */
function addInitDependency(service: ServiceDefinition, initServiceName: string): void {
  if (!service.depends_on) {
    service.depends_on = {};
  }

  if (Array.isArray(service.depends_on)) {
    service.depends_on = service.depends_on.reduce(
      (acc, dep) => ({ ...acc, [dep]: { condition: "service_started" } }),
      {}
    );
  }

  (service.depends_on as Record<string, { condition?: string }>)[initServiceName] = {
    condition: "service_completed_successfully",
  };
}

/**
 * Load and transform an upstream compose file for a service
 * Returns null if service doesn't have upstream config
 */
export async function loadTransformedUpstream(
  serviceName: string
): Promise<ComposeFile | null> {
  const servicePath = `${paths.home}/${serviceName}`;
  const config = await loadUpstreamConfig(servicePath);

  if (!config) {
    return null;
  }

  // Resolve source path relative to service directory
  const sourcePath = `${servicePath}/${config.source}`;

  try {
    const sourceContent = await Deno.readTextFile(sourcePath);
    const sourceCompose = yaml.parse(sourceContent) as ComposeFile;

    log.debug(`Transforming upstream compose for ${serviceName}`);
    return transformUpstreamCompose(sourceCompose, config, servicePath);
  } catch (err) {
    log.error(`Failed to load upstream compose for ${serviceName}: ${err}`);
    return null;
  }
}

/**
 * Find all services with harbor.yaml configurations
 */
export async function findHarborConfigServices(): Promise<string[]> {
  const services: string[] = [];

  for await (const entry of Deno.readDir(paths.home)) {
    if (entry.isDirectory && !entry.name.startsWith(".")) {
      if (await hasHarborConfig(entry.name)) {
        services.push(entry.name);
      }
    }
  }

  return services;
}

/**
 * Find all services with upstream configurations
 */
export async function findUpstreamServices(): Promise<string[]> {
  const services: string[] = [];

  for await (const entry of Deno.readDir(paths.home)) {
    if (entry.isDirectory && !entry.name.startsWith(".")) {
      if (await hasUpstreamConfig(entry.name)) {
        services.push(entry.name);
      }
    }
  }

  return services;
}
