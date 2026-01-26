/**
 * TypeScript Compose System - Type Definitions
 *
 * This module defines the types used by the TypeScript compose system.
 * TypeScript compose modules can mutate the compose object after YAML merge.
 */

export interface ComposeObject {
  services: Record<string, ServiceDefinition>;
  volumes?: Record<string, unknown>;
  networks?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface ServiceDefinition {
  image?: string;
  container_name?: string;
  command?: string | string[];
  volumes?: string[];
  environment?: Record<string, string> | string[];
  ports?: string[];
  depends_on?: string[] | Record<string, unknown>;
  networks?: string[];
  healthcheck?: unknown;
  [key: string]: unknown;
}

export interface ComposeContext {
  /**
   * Full compose object (all services, can be mutated)
   */
  compose: ComposeObject;

  /**
   * Current service handle (null for base/cross-files)
   */
  service: string | null;

  /**
   * Active services list from selectors (includes defaults)
   */
  services: string[];

  /**
   * Explicitly requested services (excludes defaults)
   */
  explicitServices: string[];

  /**
   * Active capabilities from selectors
   */
  capabilities: string[];

  /**
   * Remaining CLI args after flag/selector consumption
   */
  args: string[];

  /**
   * Compose scan directory (resolved absolute path)
   */
  dir: string;

  /**
   * Whether merge/transform pipeline is enabled
   */
  mergeEnabled: boolean;

  /**
   * Environment helpers wrapping envManager
   */
  env: {
    getValue: (key: string) => Promise<string>;
    getJsonValue: (key: string) => Promise<any>;
  };

  /**
   * List of matched compose files (YAML + TS)
   */
  files: {
    yaml: string[];
    typescript: string[];
  };
}

/**
 * TypeScript compose module interface.
 * Each module exports a default apply() function.
 */
export type ComposeModuleApply = (ctx: ComposeContext) => Promise<ComposeObject> | ComposeObject;

/**
 * Error types for TypeScript compose system
 */
export class ComposeModuleError extends Error {
  constructor(message: string, public modulePath?: string) {
    super(message);
    this.name = 'ComposeModuleError';
  }
}

export class ComposeModuleLoadError extends ComposeModuleError {
  constructor(modulePath: string, cause: Error) {
    super(`Failed to load module ${modulePath}: ${cause.message}`, modulePath);
    this.cause = cause;
  }
}

export class ComposeModuleExecutionError extends ComposeModuleError {
  constructor(modulePath: string, cause: Error) {
    super(`Error executing module ${modulePath}: ${cause.message}`, modulePath);
    this.cause = cause;
  }
}
