#!/usr/bin/env deno
/**
 * Harbor Startup Computation Tests
 * 
 * Tests the startup wave computation logic that determines the order
 * services should be started based on their dependencies.
 * 
 * Usage:
 *   deno test --allow-read --allow-env routines/tests/test_startup_computation.js
 */

import { assertEquals, assertThrows } from "https://deno.land/std@0.208.0/assert/mod.ts";
import { resolveComposeFiles } from '../docker.js';
import { readYamlConfig } from '../config.js';

/**
 * Extract dependency graph from Harbor compose files
 */
async function extractAllDependencies(containerServices, nativeServices) {
    const allServices = [...containerServices, ...nativeServices];
    const composeFiles = await resolveComposeFiles(allServices, []);
    
    const dependencyGraph = new Map();
    
    // Initialize empty dependency sets
    allServices.forEach(service => dependencyGraph.set(service, new Set()));
    
    // Extract dependencies from each compose file
    for (const file of composeFiles) {
        try {
            const config = await readYamlConfig(file, {});
            
            if (!config.services) continue;
            
            // Process each service in the compose file
            for (const [serviceName, serviceConfig] of Object.entries(config.services)) {
                // Only process services we're actually starting
                if (!allServices.includes(serviceName)) continue;
                
                if (!serviceConfig.depends_on) continue;
                
                // Handle both depends_on formats:
                // Array format: depends_on: ["service1", "service2"]
                // Object format: depends_on: { service1: { condition: "service_healthy" } }
                const dependencies = Array.isArray(serviceConfig.depends_on)
                    ? serviceConfig.depends_on
                    : Object.keys(serviceConfig.depends_on);
                
                // Add dependencies that are in our service list
                dependencies.forEach(dep => {
                    if (allServices.includes(dep)) {
                        dependencyGraph.get(serviceName).add(dep);
                    }
                });
            }
            
        } catch (error) {
            console.warn(`Failed to process compose file ${file}: ${error.message}`);
        }
    }
    
    return dependencyGraph;
}

/**
 * Compute parallel startup waves using topological sorting (Kahn's algorithm)
 */
function computeParallelWaves(graph, allServices) {
    // Step 1: Calculate in-degree (number of dependencies) for each service
    const inDegree = new Map();
    allServices.forEach(service => inDegree.set(service, 0));
    
    // Count dependencies for each service
    for (const [service, dependencies] of graph) {
        inDegree.set(service, dependencies.size);
    }
    
    const waves = [];
    
    // Step 2: Find services with no dependencies (can start immediately)
    let currentWave = allServices.filter(service => inDegree.get(service) === 0);
    
    if (currentWave.length === 0) {
        throw new Error("Circular dependencies detected - no services can start");
    }
    
    let iteration = 0;
    const maxIterations = allServices.length + 1; // Safety check
    
    // Step 3: Process waves until all services are ordered
    while (currentWave.length > 0 && iteration < maxIterations) {
        iteration++;
        
        // All services in currentWave can start in parallel
        waves.push([...currentWave]);
        
        const nextWave = [];
        
        // Step 4: "Remove" current wave services from the graph
        for (const completedService of currentWave) {
            // Find all services that depend on this completed service
            for (const [service, dependencies] of graph) {
                if (dependencies.has(completedService)) {
                    // Reduce dependency count
                    const newCount = inDegree.get(service) - 1;
                    inDegree.set(service, newCount);
                    
                    // If all dependencies satisfied, service is ready for next wave
                    if (newCount === 0) {
                        nextWave.push(service);
                    }
                }
            }
        }
        
        currentWave = nextWave;
    }
    
    // Step 5: Cycle detection - check if all services were processed
    const unprocessed = allServices.filter(service => inDegree.get(service) > 0);
    if (unprocessed.length > 0) {
        throw new Error(`Circular dependencies detected: ${unprocessed.join(', ')}`);
    }
    
    return waves;
}

/**
 * Main startup computation function
 */
async function computeStartupWaves(containerServices, nativeServices) {
    const allServices = [...containerServices, ...nativeServices];
    
    // Extract dependencies from Harbor compose files
    const dependencyGraph = await extractAllDependencies(containerServices, nativeServices);
    
    // Compute parallel waves using topological sorting
    const waves = computeParallelWaves(dependencyGraph, allServices);
    
    return {
        success: true,
        waves: waves,
        analysis: {
            hasCycles: false,
            totalServices: allServices.length,
            dependencies: Object.fromEntries(dependencyGraph)
        }
    };
}

// Test Cases

Deno.test("computeStartupWaves - simple case with no dependencies", async () => {
    const result = await computeStartupWaves(['webui'], []);
    
    assertEquals(result.success, true);
    assertEquals(result.waves.length, 1);
    assertEquals(result.waves[0], ['webui']);
    assertEquals(result.analysis.totalServices, 1);
});

Deno.test("computeStartupWaves - basic dependency chain", async () => {
    // This test would need mock compose files or real ones
    // For now, testing the wave computation logic directly
    
    const mockGraph = new Map([
        ['webui', new Set(['ollama'])],
        ['ollama', new Set()]
    ]);
    
    const waves = computeParallelWaves(mockGraph, ['webui', 'ollama']);
    
    assertEquals(waves.length, 2);
    assertEquals(waves[0], ['ollama']); // No dependencies
    assertEquals(waves[1], ['webui']); // Depends on ollama
});

Deno.test("computeParallelWaves - parallel services", () => {
    const mockGraph = new Map([
        ['api1', new Set(['database'])],
        ['api2', new Set(['database'])],
        ['database', new Set()]
    ]);
    
    const waves = computeParallelWaves(mockGraph, ['api1', 'api2', 'database']);
    
    assertEquals(waves.length, 2);
    assertEquals(waves[0], ['database']); // Root service
    assertEquals(waves[1].sort(), ['api1', 'api2']); // Both depend only on database
});

Deno.test("computeParallelWaves - complex dependency chain", () => {
    const mockGraph = new Map([
        ['web', new Set(['api'])],
        ['api', new Set(['database'])],
        ['database', new Set()]
    ]);
    
    const waves = computeParallelWaves(mockGraph, ['web', 'api', 'database']);
    
    assertEquals(waves.length, 3);
    assertEquals(waves[0], ['database']);
    assertEquals(waves[1], ['api']);
    assertEquals(waves[2], ['web']);
});

Deno.test("computeParallelWaves - circular dependency detection", () => {
    const mockGraph = new Map([
        ['service1', new Set(['service2'])],
        ['service2', new Set(['service1'])]
    ]);
    
    assertThrows(
        () => computeParallelWaves(mockGraph, ['service1', 'service2']),
        Error,
        "Circular dependencies detected"
    );
});

Deno.test("computeParallelWaves - mixed parallel and sequential", () => {
    const mockGraph = new Map([
        ['web', new Set(['api1', 'api2'])],
        ['api1', new Set(['database'])],
        ['api2', new Set(['database'])],
        ['database', new Set()]
    ]);
    
    const waves = computeParallelWaves(mockGraph, ['web', 'api1', 'api2', 'database']);
    
    assertEquals(waves.length, 3);
    assertEquals(waves[0], ['database']);
    assertEquals(waves[1].sort(), ['api1', 'api2']);
    assertEquals(waves[2], ['web']);
});