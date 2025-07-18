#!/usr/bin/env deno
/**
 * Harbor Dependency Extraction Tests
 * 
 * Tests the dependency extraction logic that parses Harbor compose files
 * to understand service dependencies.
 * 
 * Usage:
 *   deno test --allow-read --allow-env routines/tests/test_dependency_extraction.js
 */

import { assertEquals, assertExists } from "https://deno.land/std@0.208.0/assert/mod.ts";
import { resolveComposeFiles } from '../docker.js';
import { readYamlConfig } from '../config.js';

/**
 * Test dependency extraction from compose files
 */
async function testDependencyExtraction(containerServices, nativeServices) {
    const allServices = [...containerServices, ...nativeServices];
    const composeFiles = await resolveComposeFiles(allServices, []);
    
    const dependencyInfo = {
        totalFiles: composeFiles.length,
        servicesDefined: new Set(),
        dependenciesFound: new Map(),
        errors: []
    };
    
    // Process each compose file
    for (const file of composeFiles) {
        try {
            const config = await readYamlConfig(file, {});
            
            if (!config.services) {
                continue;
            }
            
            // Process each service in the compose file
            for (const [serviceName, serviceConfig] of Object.entries(config.services)) {
                dependencyInfo.servicesDefined.add(serviceName);
                
                if (!serviceConfig.depends_on) {
                    continue;
                }
                
                // Handle both depends_on formats
                const dependencies = Array.isArray(serviceConfig.depends_on)
                    ? serviceConfig.depends_on
                    : Object.keys(serviceConfig.depends_on);
                
                // Store dependencies for services we're actually starting
                if (allServices.includes(serviceName)) {
                    const filteredDeps = dependencies.filter(dep => allServices.includes(dep));
                    if (filteredDeps.length > 0) {
                        dependencyInfo.dependenciesFound.set(serviceName, filteredDeps);
                    }
                }
            }
            
        } catch (error) {
            dependencyInfo.errors.push({
                file: file,
                error: error.message
            });
        }
    }
    
    return dependencyInfo;
}

/**
 * Test compose file resolution
 */
async function testComposeFileResolution(services) {
    const composeFiles = await resolveComposeFiles(services, []);
    
    return {
        requestedServices: services,
        resolvedFiles: composeFiles,
        fileCount: composeFiles.length,
        hasBaseCompose: composeFiles.some(f => f.includes('compose.yml')),
        hasServiceFiles: composeFiles.some(f => f.includes('compose.') && !f.includes('compose.yml')),
        hasCrossServiceFiles: composeFiles.some(f => f.includes('compose.x.'))
    };
}

// Test Cases

Deno.test("compose file resolution - single service", async () => {
    const result = await testComposeFileResolution(['webui']);
    
    assertEquals(result.requestedServices, ['webui']);
    assertExists(result.resolvedFiles);
    assertEquals(result.fileCount > 0, true);
    assertEquals(result.hasBaseCompose, true);
});

Deno.test("compose file resolution - multiple services", async () => {
    const result = await testComposeFileResolution(['webui', 'ollama']);
    
    assertEquals(result.requestedServices, ['webui', 'ollama']);
    assertExists(result.resolvedFiles);
    assertEquals(result.fileCount > 0, true);
    assertEquals(result.hasBaseCompose, true);
    assertEquals(result.hasServiceFiles, true);
});

Deno.test("dependency extraction - webui service", async () => {
    const result = await testDependencyExtraction(['webui'], []);
    
    assertEquals(result.totalFiles > 0, true);
    assertEquals(result.servicesDefined.has('webui'), true);
    assertEquals(result.errors.length, 0);
});

Deno.test("dependency extraction - services with dependencies", async () => {
    // Test with services that are likely to have dependencies
    const result = await testDependencyExtraction(['librechat', 'librechat-db'], []);
    
    assertEquals(result.totalFiles > 0, true);
    assertEquals(result.servicesDefined.has('librechat'), true);
    assertEquals(result.errors.length, 0);
    
    // librechat typically depends on librechat-db
    if (result.dependenciesFound.has('librechat')) {
        const librechatDeps = result.dependenciesFound.get('librechat');
        assertEquals(Array.isArray(librechatDeps), true);
        assertEquals(librechatDeps.length > 0, true);
    }
});

Deno.test("dependency extraction - complex service chain", async () => {
    // Test with a complex service that has multiple dependencies
    const services = ['librechat', 'librechat-db', 'librechat-rag', 'librechat-search', 'librechat-vector'];
    const result = await testDependencyExtraction(services, []);
    
    assertEquals(result.totalFiles > 0, true);
    assertEquals(result.errors.length, 0);
    
    // Should find multiple services defined
    assertEquals(result.servicesDefined.size >= 2, true);
    
    // Should find some dependencies
    const totalDependencies = Array.from(result.dependenciesFound.values())
        .reduce((sum, deps) => sum + deps.length, 0);
    assertEquals(totalDependencies > 0, true);
});

Deno.test("dependency extraction - error handling", async () => {
    // Test with non-existent service to check error handling
    const result = await testDependencyExtraction(['nonexistent-service'], []);
    
    // Should not crash, should handle gracefully
    assertEquals(result.totalFiles >= 0, true);
    assertEquals(Array.isArray(result.errors), true);
});

Deno.test("dependency extraction - native service exclusion", async () => {
    // Test with native services excluded
    const result = await testDependencyExtraction(['webui'], ['ollama']);
    
    assertEquals(result.totalFiles > 0, true);
    assertEquals(result.errors.length, 0);
    
    // Should still process webui even with ollama excluded
    assertEquals(result.servicesDefined.has('webui'), true);
});

Deno.test("compose file resolution - cross-service files", async () => {
    // Test services that are likely to have cross-service files
    const result = await testComposeFileResolution(['webui', 'searxng']);
    
    assertEquals(result.requestedServices, ['webui', 'searxng']);
    assertEquals(result.fileCount > 0, true);
    assertEquals(result.hasBaseCompose, true);
    assertEquals(result.hasServiceFiles, true);
    
    // These services likely have cross-service integration
    // This is more of a regression test for the compose file resolution
});

Deno.test("dependency extraction - dependency format handling", async () => {
    const result = await testDependencyExtraction(['perplexica', 'perplexica-be'], []);
    
    assertEquals(result.totalFiles > 0, true);
    assertEquals(result.errors.length, 0);
    
    // perplexica typically depends on perplexica-be
    if (result.dependenciesFound.has('perplexica')) {
        const perplexicaDeps = result.dependenciesFound.get('perplexica');
        assertEquals(Array.isArray(perplexicaDeps), true);
        
        // Should handle both array and object formats of depends_on
        assertEquals(perplexicaDeps.includes('perplexica-be'), true);
    }
});