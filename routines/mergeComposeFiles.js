import * as yaml from "jsr:@std/yaml";
import { deepMerge } from "jsr:@std/collections/deep-merge";

import { paths } from "./paths";
import { getArgs, log } from "./utils";
import { composeCommand, resolveComposeFiles } from "./docker";

export async function mergeComposeFiles(args) {
  const { serviceOptions, excludeServices, outputFile } = parseHarborArgs(args);
  const sourceFiles = await resolveComposeFiles(serviceOptions, excludeServices);

  // Determine output file path
  const outputPath = outputFile || paths.mergedYaml;

  // Merge all files into a single file
  // to avoid docker-compose own merge logic that is very slow for
  // larger amount of files
  const contents = await Promise.all(
    sourceFiles.map(async (file) => {
      let content = await Deno.readTextFile(file);

      // Apply template substitution for native contract files
      if (file.includes('_native.yml')) {
        content = await processNativeContractTemplates(content, file);
      }

      return yaml.parse(content);
    })
  );

  let merged = contents.reduce((acc, next) => deepMerge(acc, next), {});

  // Process Harbor-specific metadata for native service integration
  merged = await processHarborMetadata(merged);

  await Deno.writeTextFile(outputPath, yaml.stringify(merged));

  // Communicate the command back to bash
  console.log(composeCommand(`-f ${paths.home}/${outputPath}`));
}

/**
 * Parse Harbor-specific arguments for compose file merging
 * Supports: -x/--exclude <services...>, --output <file>, service options
 * Format: [-x service1 service2] [--output file] [service_options...]
 */
function parseHarborArgs(args) {
  const result = {
    serviceOptions: [],
    excludeServices: [],
    outputFile: null
  };

  let i = 0;
  while (i < args.length) {
    const arg = args[i];

    if (arg === '-x' || arg === '--exclude') {
      i++; // Skip the flag
      // Collect services until next flag, '--', or end
      while (i < args.length && !args[i].startsWith('-') && args[i] !== '--') {
        const service = args[i];
        if (isValidServiceName(service)) {
          result.excludeServices.push(service);
          log.debug(`Will exclude service: ${service}`);
        } else {
          log.warn(`Invalid service name for exclusion: ${service}`);
        }
        i++;
      }
      // If we hit '--', skip it and continue with service options
      if (args[i] === '--') {
        i++;
      }
    } else if (arg === '--output') {
      if (i + 1 < args.length) {
        result.outputFile = args[i + 1];
        i += 2;
      } else {
        log.warn('--output flag requires a filename');
        i++;
      }
    } else if (arg === '--') {
      // Skip separator and treat rest as service options
      i++;
      while (i < args.length) {
        result.serviceOptions.push(args[i]);
        i++;
      }
    } else {
      // All other arguments are service options
      result.serviceOptions.push(arg);
      i++;
    }
  }

  log.debug(`Parsed args - Services: ${result.serviceOptions.length}, Exclusions: ${result.excludeServices.length}`);
  return result;
}

/**
 * Validate service name format
 */
function isValidServiceName(name) {
  return typeof name === 'string' &&
         name.length > 0 &&
         /^[a-zA-Z0-9_-]+$/.test(name);
}

/**
 * Process template variables in native contract files
 * Substitutes {{.native_port}} and other template variables with actual values
 */
async function processNativeContractTemplates(content, filePath) {
  try {
    // Extract service name from file path (e.g., "ollama/ollama_native.yml" -> "ollama")
    const serviceName = filePath.replace(/.*\/([^/]+)_native\.yml$/, '$1');

    // Parse the native contract to get the port value
    const nativeContract = yaml.parse(content);
    const nativeMetadata = nativeContract?.services?.[serviceName]?.['x-harbor-native'];

    if (!nativeMetadata) {
      log.debug(`No native metadata found in ${filePath}, skipping template processing`);
      return content;
    }

    const nativePort = nativeMetadata.port || '8080'; // Default fallback

    // Substitute template variables
    let processedContent = content;
    processedContent = processedContent.replace(/\{\{\.native_port\}\}/g, nativePort);

    log.debug(`Processed native contract templates for ${serviceName}, port: ${nativePort}`);
    return processedContent;

  } catch (error) {
    log.warn(`Failed to process native contract templates for ${filePath}: ${error.message}`);
    return content; // Return original content on error
  }
}

/**
 * Process Harbor-specific metadata in compose files
 * Handles x-harbor-config-templates and x-harbor-shared-volumes
 */
async function processHarborMetadata(composeDef) {
  if (!composeDef.services) {
    return composeDef;
  }

  for (const [serviceName, service] of Object.entries(composeDef.services)) {
    // Process config templates
    if (service['x-harbor-config-templates']) {
      await processConfigTemplates(service, serviceName);
      delete service['x-harbor-config-templates']; // Remove metadata
    }

    // Process shared volumes
    if (service['x-harbor-shared-volumes']) {
      processSharedVolumes(service, serviceName);
      delete service['x-harbor-shared-volumes']; // Remove metadata
    }
  }

  return composeDef;
}

/**
 * Process x-harbor-config-templates metadata
 * Adds envsubst command and volumes for template rendering
 */
async function processConfigTemplates(service, serviceName) {
  const templates = service['x-harbor-config-templates'];
  if (!Array.isArray(templates)) {
    log.warn(`x-harbor-config-templates must be an array for service ${serviceName}`);
    return;
  }

  const envsubstCommands = [];
  const volumes = service.volumes || [];

  for (const template of templates) {
    if (!template.source || !template.target) {
      log.warn(`Template missing source or target for service ${serviceName}`);
      continue;
    }

    // Add volume mount for the template
    volumes.push(`${template.source}:${template.target}.template:ro`);

    // Add envsubst command to render the template
    envsubstCommands.push(
      `envsubst < ${template.target}.template > ${template.target}`
    );

    log.debug(`Added config template: ${template.source} -> ${template.target} for ${serviceName}`);
  }

  // Update service volumes
  service.volumes = volumes;

  // Wrap existing command with envsubst preprocessing
  if (envsubstCommands.length > 0) {
    const originalCommand = service.command || service.entrypoint || '';
    const renderCommands = envsubstCommands.join(' && ');

    if (originalCommand) {
      service.command = `/bin/sh -c "${renderCommands} && ${originalCommand}"`;
    } else {
      service.command = `/bin/sh -c "${renderCommands}"`;
    }

    log.debug(`Updated command for ${serviceName} to include config template rendering`);
  }
}

/**
 * Process x-harbor-shared-volumes metadata
 * Conditionally adds volume mounts based on environment variables
 */
function processSharedVolumes(service, serviceName) {
  const sharedVolumes = service['x-harbor-shared-volumes'];
  if (!Array.isArray(sharedVolumes)) {
    log.warn(`x-harbor-shared-volumes must be an array for service ${serviceName}`);
    return;
  }

  const volumes = service.volumes || [];

  for (const volume of sharedVolumes) {
    if (!volume.source_variable || !volume.target) {
      log.warn(`Shared volume missing source_variable or target for service ${serviceName}`);
      continue;
    }

    // Check if the environment variable is defined
    const hostPath = Deno.env.get(volume.source_variable);
    if (hostPath && hostPath.trim() !== '') {
      // Build volume specification
      const readOnlyFlag = volume.read_only ? ':ro' : '';
      const volumeSpec = `${hostPath}:${volume.target}${readOnlyFlag}`;

      volumes.push(volumeSpec);
      log.debug(`Added shared volume: ${volumeSpec} for ${serviceName}`);
    } else {
      log.debug(`Skipping shared volume for ${serviceName}: ${volume.source_variable} not defined`);
    }
  }

  // Update service volumes
  service.volumes = volumes;
}

if (import.meta.main === true) {
  const args = getArgs();
  mergeComposeFiles(args).catch((err) => log(err));
}