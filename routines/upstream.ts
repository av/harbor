import * as yaml from "jsr:@std/yaml";
import { paths } from "./paths";
import { log } from "./utils";

export interface UpstreamConfig {
  source: string;
  namespace: string;
  services?: {
    include?: string[];
    exclude?: string[];
  };
  expose?: string[];  // Services exposed on harbor-network with alias
  init?: {
    image: string;
    script: string;
    volumes?: string[];
  };
  // Deprecated - kept for backward compatibility
  prefix?: string;
  include?: string[];
  exclude?: string[];
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

/**
 * Volume can be either a string (short syntax) or an object (long syntax)
 */
type VolumeEntry = string | {
  type?: string;
  source?: string;
  target?: string;
  read_only?: boolean;
  [key: string]: unknown;
};

export interface ServiceDefinition {
  container_name?: string;
  depends_on?: string[] | Record<string, { condition?: string }>;
  networks?: string[] | Record<string, unknown>;
  network_mode?: string;
  volumes?: VolumeEntry[];
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
  // Support both new schema (namespace, services.include/exclude) and old (prefix, include/exclude)
  const namespace = config.namespace || config.prefix || "upstream";
  const include = config.services?.include || config.include;
  const exclude = config.services?.exclude || config.exclude;
  const expose = config.expose || [];
  const internalNetwork = `${namespace}-internal`;

  const transformed: ComposeFile = {
    services: {},
    volumes: {},
    networks: {
      [internalNetwork]: {},  // Internal network for service isolation
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

  // Build set of exposed services
  const exposedServices = new Set<string>(expose);

  // Transform services - keep original names, add to internal network
  for (const [name, service] of Object.entries(compose.services || {})) {
    if (!includedServices.has(name)) {
      continue;
    }

    // Keep original service name (no prefixing)
    const transformedService = transformService(
      service,
      name,
      namespace,
      internalNetwork,
      exposedServices.has(name),
      servicePath
    );
    transformed.services![name] = transformedService;
  }

  // Transform volumes (prefix them to avoid conflicts)
  for (const [name, volumeConfig] of Object.entries(compose.volumes || {})) {
    const newName = `${namespace}-${name}`;
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
    transformed.services![`${namespace}-init`] = createInitContainer(config, namespace, internalNetwork, servicePath);
    
    // Make all other services depend on init
    for (const [name, service] of Object.entries(transformed.services!)) {
      if (name !== `${namespace}-init`) {
        addInitDependency(service as ServiceDefinition, `${namespace}-init`);
      }
    }
  }

  return transformed;
}

/**
 * Transform a single service definition
 * Uses internal network for isolation, with optional alias on harbor-network for exposed services
 */
function transformService(
  service: ServiceDefinition,
  originalName: string,
  namespace: string,
  internalNetwork: string,
  isExposed: boolean,
  servicePath: string
): ServiceDefinition {
  const transformed: ServiceDefinition = { ...service };

  // Set container name with harbor prefix and namespace
  transformed.container_name = `\${HARBOR_CONTAINER_PREFIX}.${namespace}-${originalName}`;

  // Build network configuration
  // All services join internal network (original names work there)
  // Exposed services also join harbor-network with prefixed alias
  const networks: Record<string, unknown> = {
    [internalNetwork]: {},  // Internal network - service reachable by original name
  };

  if (isExposed) {
    // Exposed services get alias on harbor-network
    networks["harbor-network"] = {
      aliases: [`${namespace}-${originalName}`],
    };
  }

  // Handle network_mode: service:X - these services share network with another
  // Don't add networks if using network_mode
  if (!transformed.network_mode) {
    transformed.networks = networks;
  }
  // Note: network_mode references stay unchanged - they reference original service names
  // which work because all services are on the internal network

  // depends_on stays unchanged - references original service names (internal network)

  // Transform volume references to use prefixed named volumes
  if (transformed.volumes) {
    transformed.volumes = transformVolumes(transformed.volumes, namespace, servicePath);
  }

  // Add env_file for harbor integration
  const serviceDir = servicePath.split("/").pop();
  const envFiles = [
    "./.env",
    `./${serviceDir}/override.env`,
  ];
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
 * Transform volume mounts to use prefixed named volumes
 * Handles both short syntax (string) and long syntax (object)
 */
function transformVolumes(
  volumes: VolumeEntry[],
  prefix: string,
  servicePath: string
): VolumeEntry[] {
  return volumes.map((vol) => {
    // Handle long syntax (object format)
    if (typeof vol === "object" && vol !== null) {
      const transformed = { ...vol };
      // Only transform named volumes (type: volume), not bind mounts
      if (transformed.type === "volume" && transformed.source) {
        transformed.source = `${prefix}-${transformed.source}`;
      }
      return transformed;
    }

    // Handle short syntax (string format)
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
  namespace: string,
  internalNetwork: string,
  servicePath: string
): ServiceDefinition {
  const serviceDir = servicePath.split("/").pop();
  const init: ServiceDefinition = {
    image: config.init!.image,
    container_name: `\${HARBOR_CONTAINER_PREFIX}.${namespace}-init`,
    command: ["sh", `-c`, `sh /scripts/init.sh`],
    volumes: [
      `./${serviceDir}/${config.init!.script}:/scripts/init.sh:ro`,
      ...(config.init!.volumes || []).map((v) =>
        v.replace("{namespace}", namespace)
      ),
    ],
    networks: [internalNetwork],
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
