/**
 * @fileoverview Harbor Compose File Merger
 *
 * This module provides a unified interface for Harbor's Docker Compose operations.
 * It supports two primary modes:
 * 1. Service Discovery: Extract and list service names from compose files
 * 2. Command Generation: Merge compose files and generate docker compose commands
 *
 * The implementation follows DRY principles and maintains consistency across
 * all Harbor compose operations.
 *
 * @author Harbor Team
 * @version 2.0.0
 */

import * as yaml from "jsr:@std/yaml";
import { deepMerge } from "jsr:@std/collections/deep-merge";

import { paths } from "./paths";
import { getArgs, log } from "./utils";
import { composeCommand, resolveComposeFiles } from "./docker";

/**
 * Main entry point for Harbor compose file operations
 * Supports two modes: service discovery and command generation
 *
 * @param {string[]} args - Command line arguments
 * @returns {Promise<void>} - Outputs results to stdout
 */
export async function mergeComposeFiles(args) {
  const { outputType, serviceOptions, excludeServices, outputFile } = parseHarborArgs(args);
  const sourceFiles = await resolveComposeFiles(serviceOptions, excludeServices);

  if (outputType === "services") {
    return await handleServiceDiscovery(sourceFiles);
  }

  return await handleCommandGeneration(sourceFiles, outputFile);
}

/**
 * Handle service discovery mode - extract and output service names
 * @param {string[]} sourceFiles - Array of compose file paths to process
 * @returns {Promise<void>} - Outputs service names to stdout
 */
async function handleServiceDiscovery(sourceFiles) {
  const services = await extractServiceNames(sourceFiles);

  // Output service names one per line for bash consumption
  services.forEach(service => console.log(service));
}

/**
 * Handle command generation mode - create merged compose file and output command
 */
async function handleCommandGeneration(sourceFiles, outputFile) {
  const outputPath = outputFile || paths.mergedYaml;

  // Process and merge all compose files
  const mergedCompose = await processAndMergeFiles(sourceFiles);

  // Write the merged file
  await Deno.writeTextFile(outputPath, yaml.stringify(mergedCompose));

  // Output the docker compose command for bash
  console.log(composeCommand(`-f ${paths.home}/${outputPath}`));
}

/**
 * Process all compose files and merge them into a single definition
 */
async function processAndMergeFiles(sourceFiles) {
  const processedContents = await Promise.all(
    sourceFiles.map(processComposeFile)
  );

  const merged = processedContents.reduce((acc, next) => deepMerge(acc, next), {});

  // Process Harbor-specific metadata
  return await processHarborMetadata(merged);
}

/**
 * Process a single compose file (load, parse, apply templates)
 */
async function processComposeFile(filePath) {
  let content = await readFileWithErrorHandling(filePath);

  // Apply template substitution for native contract files
  if (isNativeContractFile(filePath)) {
    content = await processNativeContractTemplates(content, filePath);
  }

  return parseYamlWithErrorHandling(content, filePath);
}

/**
 * Utility functions for consistent error handling
 */
async function readFileWithErrorHandling(filePath) {
  try {
    return await Deno.readTextFile(filePath);
  } catch (error) {
    log.warn(`Failed to read file ${filePath}: ${error.message}`);
    throw error;
  }
}

function parseYamlWithErrorHandling(content, filePath) {
  try {
    return yaml.parse(content);
  } catch (error) {
    log.warn(`Failed to parse YAML in ${filePath}: ${error.message}`);
    throw error;
  }
}

function isNativeContractFile(filePath) {
  return filePath.includes('_native.yml');
}

/**
 * Parse Harbor-specific arguments for compose file merging
 * Supports: --output-type=<type>, -x/--exclude <services...>, --output <file>, service options
 * Format: [--output-type=<services|command>] [-x service1 service2] [--output file] [service_options...]
 */
function parseHarborArgs(args) {
  const result = {
    outputType: "command", // Default to backward compatibility
    serviceOptions: [],
    excludeServices: [],
    outputFile: null
  };

  const handlers = {
    '--output-type': handleOutputType,
    '-x': handleExcludeServices,
    '--exclude': handleExcludeServices,
    '--output': handleOutputFile,
    '--': handleSeparator
  };

  let i = 0;
  while (i < args.length) {
    const arg = args[i];

    if (arg.startsWith('--output-type=')) {
      i = handlers['--output-type'](args, i, result);
    } else if (handlers[arg]) {
      i = handlers[arg](args, i, result);
    } else {
      // All other arguments are service options
      result.serviceOptions.push(arg);
      i++;
    }
  }

  log.debug(`Parsed args - Output: ${result.outputType}, Services: ${result.serviceOptions.length}, Exclusions: ${result.excludeServices.length}`);
  return result;

  // Handler functions for different argument types
  function handleOutputType(args, index, result) {
    const outputType = args[index].split('=')[1];
    validateOutputType(outputType);
    result.outputType = outputType;
    return index + 1;
  }

  function handleExcludeServices(args, index, result) {
    let i = index + 1; // Skip the flag

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

    return i;
  }

  function handleOutputFile(args, index, result) {
    if (index + 1 < args.length) {
      result.outputFile = args[index + 1];
      return index + 2;
    } else {
      log.warn('--output flag requires a filename');
      return index + 1;
    }
  }

  function handleSeparator(args, index, result) {
    // Skip separator and treat rest as service options
    let i = index + 1;
    while (i < args.length) {
      result.serviceOptions.push(args[i]);
      i++;
    }
    return i;
  }
}

function validateOutputType(outputType) {
  const validTypes = ['services', 'command'];
  if (!validTypes.includes(outputType)) {
    throw new Error(`Invalid output type: ${outputType}. Expected one of: ${validTypes.join(', ')}`);
  }
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
    const serviceName = extractServiceNameFromPath(filePath);
    const nativeMetadata = await extractNativeMetadata(content, serviceName, filePath);

    if (!nativeMetadata) {
      return content; // No metadata to process
    }

    return applyTemplateSubstitutions(content, nativeMetadata, serviceName);

  } catch (error) {
    log.warn(`Failed to process native contract templates for ${filePath}: ${error.message}`);
    return content; // Return original content on error
  }
}

/**
 * Extract service name from native contract file path
 */
function extractServiceNameFromPath(filePath) {
  const match = filePath.match(/.*\/([^/]+)_native\.yml$/);
  if (!match) {
    throw new Error(`Invalid native contract file path format: ${filePath}`);
  }
  return match[1];
}

/**
 * Extract native metadata from contract content
 */
async function extractNativeMetadata(content, serviceName, filePath) {
  const nativeContract = parseYamlWithErrorHandling(content, filePath);
  const nativeMetadata = nativeContract?.services?.[serviceName]?.['x-harbor-native'];

  if (!nativeMetadata) {
    log.debug(`No native metadata found in ${filePath}, skipping template processing`);
    return null;
  }

  return nativeMetadata;
}

/**
 * Apply template substitutions to content
 */
function applyTemplateSubstitutions(content, nativeMetadata, serviceName) {
  const nativePort = nativeMetadata.port || '8080'; // Default fallback

  // Define template mappings - easily extensible for new templates
  const templateMappings = {
    '{{.native_port}}': nativePort,
    // Future templates can be added here
  };

  let processedContent = content;
  for (const [template, replacement] of Object.entries(templateMappings)) {
    processedContent = processedContent.replace(new RegExp(escapeRegExp(template), 'g'), replacement);
  }

  log.debug(`Processed native contract templates for ${serviceName}, port: ${nativePort}`);
  return processedContent;
}

/**
 * Escape special regex characters in template strings
 */
function escapeRegExp(string) {
  return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Process Harbor-specific metadata in compose files
 * Handles x-harbor-config-templates and x-harbor-shared-volumes
 */
async function processHarborMetadata(composeDef) {
  if (!composeDef?.services) {
    return composeDef;
  }

  for (const [serviceName, service] of Object.entries(composeDef.services)) {
    await processServiceMetadata(service, serviceName);
  }

  return composeDef;
}

/**
 * Process all metadata for a single service
 */
async function processServiceMetadata(service, serviceName) {
  const processors = [
    { key: 'x-harbor-config-templates', handler: processConfigTemplates },
    { key: 'x-harbor-shared-volumes', handler: processSharedVolumes }
  ];

  for (const { key, handler } of processors) {
    if (service[key]) {
      await handler(service, serviceName, service[key]);
      delete service[key]; // Remove metadata after processing
    }
  }
}

/**
 * Shared utilities for volume and validation handling
 */
const ServiceUtils = {
  /**
   * Ensure service has volumes array and return it
   */
  ensureVolumes(service) {
    service.volumes = service.volumes || [];
    return service.volumes;
  },

  /**
   * Validate that metadata is an array
   */
  validateArray(metadata, metadataType, serviceName) {
    if (!Array.isArray(metadata)) {
      log.warn(`${metadataType} must be an array for service ${serviceName}`);
      return false;
    }
    return true;
  },

  /**
   * Validate required fields on an object
   */
  validateRequiredFields(obj, requiredFields, context) {
    for (const field of requiredFields) {
      if (!obj[field]) {
        log.warn(`${context} missing required field: ${field}`);
        return false;
      }
    }
    return true;
  },

  /**
   * Update service command with preprocessing
   */
  updateServiceCommand(service, preprocessCommands) {
    if (preprocessCommands.length === 0) return;

    const originalCommand = service.command || service.entrypoint || '';
    const renderCommands = preprocessCommands.join(' && ');

    service.command = originalCommand
      ? `/bin/sh -c "${renderCommands} && ${originalCommand}"`
      : `/bin/sh -c "${renderCommands}"`;
  }
};

/**
 * Process x-harbor-config-templates metadata
 * Adds envsubst command and volumes for template rendering
 */
async function processConfigTemplates(service, serviceName, templates) {
  if (!ServiceUtils.validateArray(templates, 'x-harbor-config-templates', serviceName)) {
    return;
  }

  const envsubstCommands = [];
  const volumes = ServiceUtils.ensureVolumes(service);

  for (const template of templates) {
    if (!ServiceUtils.validateRequiredFields(template, ['source', 'target'], `Template for service ${serviceName}`)) {
      continue;
    }

    // Add volume mount for the template
    volumes.push(`${template.source}:${template.target}.template:ro`);

    // Add envsubst command to render the template
    envsubstCommands.push(`envsubst < ${template.target}.template > ${template.target}`);

    log.debug(`Added config template: ${template.source} -> ${template.target} for ${serviceName}`);
  }

  // Update service command with preprocessing
  ServiceUtils.updateServiceCommand(service, envsubstCommands);

  if (envsubstCommands.length > 0) {
    log.debug(`Updated command for ${serviceName} to include config template rendering`);
  }
}

/**
 * Process x-harbor-shared-volumes metadata
 * Conditionally adds volume mounts based on environment variables
 */
function processSharedVolumes(service, serviceName, sharedVolumes) {
  if (!ServiceUtils.validateArray(sharedVolumes, 'x-harbor-shared-volumes', serviceName)) {
    return;
  }

  const volumes = ServiceUtils.ensureVolumes(service);

  for (const volume of sharedVolumes) {
    if (!ServiceUtils.validateRequiredFields(volume, ['source_variable', 'target'], `Shared volume for service ${serviceName}`)) {
      continue;
    }

    // Check if the environment variable is defined
    const hostPath = Deno.env.get(volume.source_variable);
    if (hostPath?.trim()) {
      const readOnlyFlag = volume.read_only ? ':ro' : '';
      const volumeSpec = `${hostPath}:${volume.target}${readOnlyFlag}`;

      volumes.push(volumeSpec);
      log.debug(`Added shared volume: ${volumeSpec} for ${serviceName}`);
    } else {
      log.debug(`Skipping shared volume for ${serviceName}: ${volume.source_variable} not defined`);
    }
  }
}

/**
 * Extract service names from compose files for service discovery
 * @param {string[]} sourceFiles - Array of compose file paths
 * @returns {Promise<string[]>} - Array of service names, sorted alphabetically
 */
async function extractServiceNames(sourceFiles) {
  const serviceSet = new Set();

  await Promise.all(
    sourceFiles.map(async (file) => {
      try {
        const services = await extractServicesFromFile(file);
        services.forEach(service => serviceSet.add(service));
      } catch (error) {
        log.warn(`Failed to extract services from ${file}: ${error.message}`);
        // Continue processing other files
      }
    })
  );

  return Array.from(serviceSet).sort();
}

/**
 * Extract service names from a single compose file
 */
async function extractServicesFromFile(filePath) {
  const content = await readFileWithErrorHandling(filePath);
  const composeDef = parseYamlWithErrorHandling(content, filePath);

  if (!composeDef?.services) {
    log.debug(`No services found in ${filePath}`);
    return [];
  }

  const services = Object.keys(composeDef.services);
  log.debug(`Found ${services.length} services in ${filePath}: ${services.join(', ')}`);

  return services;
}

if (import.meta.main === true) {
  const args = getArgs();
  mergeComposeFiles(args).catch((err) => log(err));
}