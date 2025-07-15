// routines/startupOrder.js
//
// PURPOSE: Solve Harbor's interleaved native/container dependency problem
//
// PROBLEM: Harbor's phase-based startup (natives first, containers second) 
//          breaks when native services depend on container services
//
// EXAMPLE FAILURE:
//   Dependencies: cache(native) → api(container) → database(native)
//   Current Harbor: Start cache+database, then api → cache fails (api not ready)
//   With this fix: Start database, then api, then cache → all dependencies respected
//
// ALGORITHM: Kahn's topological sort with parallel wave computation
// REFERENCE: https://www.geeksforgeeks.org/dsa/topological-sorting-indegree-based-solution/
//
// USAGE FROM HARBOR.SH:
//   waves_output=$(run_routine startupOrder --container "${container_services[@]}" --native "${native_services[@]}")
//   # Returns: STATUS=SUCCESS, WAVE_COUNT=3, WAVE_1_CONTAINERS="api", WAVE_1_NATIVES="database", etc.
//
// INTEGRATION POINT: Called from harbor.sh run_up() function
// FALLBACK: If this fails, Harbor uses existing phase-based startup
// HARBOR INTEGRATION: Uses Harbor's proven infrastructure (config.js, docker.js, utils.js)

// Harbor system imports - reuse proven infrastructure
import { readYamlConfig } from "./config.js";
import { resolveComposeFiles } from "./docker.js";
import { log } from "./utils.js";


/**
 * Computes startup waves for mixed native/container services.
 * 
 * SOLVES: Harbor's phase-based startup limitation for interleaved dependencies
 * 
 * @param {string[]} containerServices - Services to run as containers
 * @param {string[]} nativeServices - Services to run natively (excluded from containers)
 * @returns {Promise<Object>} Analysis object with waves, cycles, and fallback data
 * 
 * EXAMPLE:
 *   Input: containerServices=["api"], nativeServices=["cache", "database"]
 *   Dependencies: cache → api → database
 *   Output: {
 *     success: true,
 *     waves: [["database"], ["api"], ["cache"]],
 *     analysis: { hasCycles: false, totalServices: 3 }
 *   }
 */
export async function computeStartupWaves(containerServices = [], nativeServices = []) {
    const allServices = [...containerServices, ...nativeServices];
    
    if (allServices.length === 0) {
        log.debug("No services to order");
        return {
            success: true,
            waves: [],
            analysis: { hasCycles: false, totalServices: 0, dependencies: {} }
        };
    }
    
    log.debug(`Computing startup waves for ${allServices.length} services:`);
    log.debug(`  Containers: ${containerServices.join(', ') || 'none'}`);
    log.debug(`  Natives: ${nativeServices.join(', ') || 'none'}`);
    
    try {
        // Extract dependencies from Harbor's compose files
        const dependencyGraph = await extractAllDependencies(containerServices, nativeServices);
        
        // Apply Kahn's algorithm to compute parallel startup waves
        const waves = computeParallelWaves(dependencyGraph, allServices);
        
        logWaveExplanation(waves, dependencyGraph);
        
        return {
            success: true,
            waves: waves,
            analysis: {
                hasCycles: false,
                totalServices: allServices.length,
                dependencies: Object.fromEntries(dependencyGraph)
            }
        };
        
    } catch (error) {
        log.warn(`Startup wave computation failed: ${error.message}`);
        
        if (error.message.includes("Circular dependencies")) {
            // Extract dependency graph for analysis even when cycles exist
            const dependencyGraph = await extractAllDependencies(containerServices, nativeServices);
            
            return {
                success: false,
                waves: null,
                analysis: {
                    hasCycles: true,
                    totalServices: allServices.length,
                    dependencies: Object.fromEntries(dependencyGraph),
                    cycles: error.message.replace("Circular dependencies detected: ", "")
                },
                fallback: nativeServices.length > 0 && containerServices.length > 0 
                    ? [nativeServices, containerServices] 
                    : [allServices]
            };
        }
        
        // For other errors, still provide fallback
        const fallbackWaves = nativeServices.length > 0 && containerServices.length > 0 
            ? [nativeServices, containerServices] 
            : [allServices];
            
        return {
            success: false,
            waves: fallbackWaves,
            analysis: {
                hasCycles: false,
                totalServices: allServices.length,
                dependencies: {},
                error: error.message
            }
        };
    }
}


/**
 * Extract service dependencies from Harbor's compose files.
 * 
 * USES: Harbor's existing compose file resolution and YAML parsing
 * HANDLES: Both array and object formats of depends_on
 * 
 * @param {string[]} containerServices 
 * @param {string[]} nativeServices 
 * @returns {Promise<Map<string, Set<string>>>} Graph: service -> Set of dependencies
 */
async function extractAllDependencies(containerServices, nativeServices) {
    // Use Harbor's compose file resolution system
    const allServices = [...containerServices, ...nativeServices];
    const composeFiles = await resolveComposeFiles(allServices, []);
    
    const dependencyGraph = new Map();
    
    // Initialize empty dependency sets
    allServices.forEach(service => dependencyGraph.set(service, new Set()));
    
    log.debug(`Extracting dependencies from ${composeFiles.length} compose files`);
    
    // Extract dependencies from each compose file
    for (const file of composeFiles) {
        try {
            const config = await readYamlConfig(file, {});
            
            if (!config.services) {
                log.debug(`No services section in ${file}`);
                continue;
            }
            
            // Process each service in the compose file
            for (const [serviceName, serviceConfig] of Object.entries(config.services)) {
                // Only process services we're actually starting
                if (!allServices.includes(serviceName)) {
                    continue;
                }
                
                if (!serviceConfig.depends_on) {
                    continue;
                }
                
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
                        log.debug(`Found dependency: ${serviceName} → ${dep}`);
                    }
                });
            }
            
        } catch (error) {
            log.debug(`Skipping dependency extraction from ${file}: ${error.message}`);
        }
    }
    
    return dependencyGraph;
}

/**
 * Kahn's algorithm implementation with parallel wave computation.
 * 
 * ALGORITHM: Standard topological sort with level computation
 * COMPLEXITY: O(V + E) time, O(V) space
 * REFERENCE: https://www.geeksforgeeks.org/dsa/topological-sorting-indegree-based-solution/
 * 
 * @param {Map<string, Set<string>>} graph - service -> dependencies mapping
 * @param {string[]} allServices - all services to order
 * @returns {string[][]} Array of waves, each wave can start in parallel
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
        throw new Error("No services without dependencies found - possible circular dependency");
    }
    
    // Step 3: Process waves until all services are ordered
    while (currentWave.length > 0) {
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
        // Find the actual cycles for better error reporting
        const cycleInfo = findCycles(graph, unprocessed);
        throw new Error(`Circular dependencies detected: ${cycleInfo}`);
    }
    
    return waves;
}

/**
 * Helper function to identify cycles for better error reporting
 */
function findCycles(graph, unprocessedServices) {
    // Simple cycle detection - find services that depend on each other
    const cycles = [];
    
    for (const service of unprocessedServices) {
        const dependencies = graph.get(service);
        for (const dep of dependencies) {
            if (unprocessedServices.includes(dep)) {
                cycles.push(`${service} → ${dep}`);
            }
        }
    }
    
    return cycles.length > 0 ? cycles.join(', ') : unprocessedServices.join(', ');
}

function logWaveExplanation(waves, dependencyGraph) {
    log.debug(`Computed ${waves.length} startup waves:`);
    waves.forEach((wave, i) => {
        log.debug(`  Wave ${i + 1}: ${wave.join(', ')} (${wave.length} services in parallel)`);
    });
    
    // Log dependency summary
    let totalDeps = 0;
    for (const [service, deps] of dependencyGraph) {
        if (deps.size > 0) {
            totalDeps += deps.size;
            log.debug(`  Dependencies: ${service} → [${Array.from(deps).join(', ')}]`);
        }
    }
    
    if (totalDeps === 0) {
        log.debug("  No dependencies found - all services can start in parallel");
    }
}

// CLI entry point for testing
if (import.meta.main) {
    const containerServices = [];
    const nativeServices = [];
    
    // Parse command line arguments: --container svc1 svc2 --native svc3 svc4
    let currentArray = containerServices;
    for (const arg of Deno.args) {
        if (arg === '--container') {
            currentArray = containerServices;
        } else if (arg === '--native') {
            currentArray = nativeServices;
        } else {
            currentArray.push(arg);
        }
    }
    
    if (containerServices.length === 0 && nativeServices.length === 0) {
        console.log("Usage: deno run --allow-read startupOrder.js --container svc1 svc2 --native svc3 svc4");
        Deno.exit(1);
    }
    
    try {
        const result = await computeStartupWaves(containerServices, nativeServices);
        
        if (!result.success && result.analysis?.hasCycles) {
            // Output bash variables for circular dependency case
            console.log('STATUS=CIRCULAR_DEPENDENCY');
            console.log(`CYCLES="${result.analysis.cycles}"`);
            Deno.exit(1);
        }
        
        if (result.waves) {
            // Output type-aware bash variables
            console.log('STATUS=SUCCESS');
            console.log(`WAVE_COUNT=${result.waves.length}`);
            
            result.waves.forEach((wave, index) => {
                const waveNum = index + 1;
                const waveContainers = wave.filter(svc => containerServices.includes(svc));
                const waveNatives = wave.filter(svc => nativeServices.includes(svc));
                
                console.log(`WAVE_${waveNum}_CONTAINERS="${waveContainers.join(' ')}"`);
                console.log(`WAVE_${waveNum}_NATIVES="${waveNatives.join(' ')}"`);
            });
        }
        
    } catch (error) {
        console.error(`Error: ${error.message}`);
        Deno.exit(1);
    }
}