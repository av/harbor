// Test script for upstream compose transformation
import * as yaml from "jsr:@std/yaml";
import { loadUpstreamConfig, transformUpstreamCompose, loadTransformedUpstream } from "./upstream.ts";
import { paths } from "./paths.ts";

async function testTransformation() {
  console.log("=== Testing Upstream Compose Transformation ===\n");

  // Test 1: Load upstream config
  console.log("1. Loading upstream config for dify2...");
  const config = await loadUpstreamConfig(`${paths.home}/dify2`);
  if (!config) {
    console.error("Failed to load upstream config!");
    Deno.exit(1);
  }
  console.log("   Config loaded:", JSON.stringify(config, null, 2));

  // Test 2: Load and transform the compose file
  console.log("\n2. Loading and transforming upstream compose...");
  const transformed = await loadTransformedUpstream("dify2");
  if (!transformed) {
    console.error("Failed to transform upstream compose!");
    Deno.exit(1);
  }

  // Test 3: Check transformed service names
  console.log("\n3. Checking transformed services...");
  const serviceNames = Object.keys(transformed.services || {});
  console.log("   Services:", serviceNames.join(", "));

  // Verify prefix was applied
  const hasPrefix = serviceNames.every(name => name.startsWith("dify2-"));
  console.log("   All services have dify2- prefix:", hasPrefix);

  // Test 4: Check a specific service transformation
  console.log("\n4. Checking dify2-api service details...");
  const apiService = transformed.services?.["dify2-api"];
  if (apiService) {
    console.log("   container_name:", apiService.container_name);
    console.log("   networks:", JSON.stringify(apiService.networks));
    console.log("   env_file:", JSON.stringify(apiService.env_file));
    
    // Check depends_on transformation
    if (apiService.depends_on) {
      console.log("   depends_on keys:", Object.keys(apiService.depends_on).join(", "));
    }
  }

  // Test 5: Check volumes transformation
  console.log("\n5. Checking transformed volumes...");
  const volumeNames = Object.keys(transformed.volumes || {});
  console.log("   Volumes:", volumeNames.join(", "));

  // Test 6: Output a sample of the transformed YAML
  console.log("\n6. Sample of transformed YAML (first 100 lines)...");
  const yamlOutput = yaml.stringify(transformed);
  const lines = yamlOutput.split("\n").slice(0, 100);
  console.log(lines.join("\n"));

  console.log("\n=== Test Complete ===");
}

testTransformation().catch(console.error);
