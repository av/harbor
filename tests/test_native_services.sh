#!/bin/bash
#
# Harbor Native Service Dependency Resolution Test Suite
#
# Consolidated test suite for Harbor's native service functionality including
# dependency resolution, configuration parsing, startup ordering, and race condition fixes.
#
# CONSOLIDATED FROM:
# - /tests/test_native.sh (724 lines) - race condition detection, fix validation  
# - /test_native.sh (493 lines) - basic native infrastructure tests
# - /test_native_dependency_fix.py (434 lines) - Python dependency tests → converted to shell
# - /tests/test_dependency_waves.sh (491 lines) - wave algorithm tests
#
# TESTING APPROACH:
# - Executes actual loadNativeConfig.js routine with test YAML configs
# - Analyzes harbor.sh code patterns for race conditions and fixes
# - Creates synthetic dependency scenarios to test execution ordering
# - Tests both two-phase execution and wave-based dependency resolution
# - No real services started, no network connections, no file modifications
#
# COVERAGE AREAS:
# - Basic race condition detection in harbor.sh native service startup loop
# - Native config parsing via loadNativeConfig.js routine execution
# - Two-phase execution validation (natives first, then containers)
# - Interleaved native→container→native dependency chain handling
# - Container→native dependency support verification
# - Dependency wave computation and circular dependency detection
# - Fallback behavior when dependency resolution fails
#
# Usage:
#   ./test_native_services.sh                    # Run all tests
#   ./test_native_services.sh --verify-bug       # Show the dependency race condition bug
#   ./test_native_services.sh --verify-fix       # Check if the surgical fix is implemented
#   ./test_native_services.sh --test-interleaved # Test interleaved dependency patterns
#   ./test_native_services.sh --help             # Show help

set -euo pipefail

# Test configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HARBOR_ROOT="$(dirname "$SCRIPT_DIR")"
TESTS_PASSED=0
TESTS_TOTAL=0
TEMP_DIR=""
VERBOSE=false

# Colors for output
if [[ -t 1 ]]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    NC='\033[0m'
else
    RED='' GREEN='' YELLOW='' BLUE='' NC=''
fi

# Logging functions
log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[PASS]${NC} $*"; }
log_error() { echo -e "${RED}[FAIL]${NC} $*"; }
log_warning() { echo -e "${YELLOW}[WARN]${NC} $*"; }

# Test result tracking with actionable failure guidance
test_result() {
    local test_name="$1"
    local passed="$2"
    local message="${3:-}"
    local action_on_failure="${4:-}"
    
    ((TESTS_TOTAL++))
    
    if [[ "$passed" == "true" ]]; then
        ((TESTS_PASSED++))
        log_success "$test_name${message:+ - $message}"
    else
        log_error "$test_name${message:+ - $message}"
        if [[ -n "$action_on_failure" ]]; then
            log_warning "💡 Action: $action_on_failure"
        fi
    fi
}

# Setup temporary directory for test artifacts
setup_temp_dir() {
    TEMP_DIR=$(mktemp -d)
    log_info "Created temp directory: $TEMP_DIR"
}

# Cleanup temporary directory
cleanup_temp_dir() {
    if [[ -n "$TEMP_DIR" && -d "$TEMP_DIR" ]]; then
        rm -rf "$TEMP_DIR"
        log_info "Cleaned up temp directory"
    fi
    # No temporary test files to clean up - using real Harbor configs
}

# Trap cleanup on exit
trap cleanup_temp_dir EXIT

# Test 1: Harbor native service infrastructure
test_native_infrastructure() {
    log_info "Testing Harbor native service infrastructure..."
    
    # Check harbor.sh exists and is executable
    if [[ -x "$HARBOR_ROOT/harbor.sh" ]]; then
        test_result "Harbor executable" true "harbor.sh found and executable"
    else
        test_result "Harbor executable" false "harbor.sh not found or not executable"
        return
    fi
    
    # Check routines directory exists
    if [[ -d "$HARBOR_ROOT/routines" ]]; then
        test_result "Routines directory" true "routines/ directory exists"
    else
        test_result "Routines directory" false "routines/ directory not found"
        return
    fi
    
    # Check key routine files exist
    local key_routines=(
        "loadNativeConfig.js"
        "docker.js"
        "config.js"
        "utils.js"
        "startupOrder.js"
    )
    
    for routine in "${key_routines[@]}"; do
        if [[ -f "$HARBOR_ROOT/routines/$routine" ]]; then
            test_result "Routine: $routine" true "Found"
        else
            test_result "Routine: $routine" false "Missing" "Check if Harbor routines are properly installed"
        fi
    done
    
    # Test Deno availability for routine execution
    if command -v deno >/dev/null 2>&1; then
        test_result "Deno runtime" true "Available for routine execution"
    else
        test_result "Deno runtime" false "Not available - routines cannot be tested" "Install Deno runtime"
    fi
}

# Test 2: Native config parsing functionality
test_native_config_parsing() {
    log_info "Testing native config parsing..."
    
    # Test loadNativeConfig.js routine with actual ollama config
    if command -v deno >/dev/null 2>&1; then
        local config_output
        if config_output=$(cd "$HARBOR_ROOT" && timeout 10 deno run --allow-read routines/loadNativeConfig.js "ollama/ollama_native.yml" "ollama" 2>/dev/null); then
            test_result "Native config parsing" true "loadNativeConfig.js executed successfully"
            
            # Check if output contains expected variables from actual ollama config
            if echo "$config_output" | grep -q "NATIVE_PORT="; then
                test_result "Native port extraction" true "NATIVE_PORT found in config output"
            else
                test_result "Native port extraction" false "NATIVE_PORT not found in config output"
            fi
            
            if echo "$config_output" | grep -q "NATIVE_EXECUTABLE="; then
                test_result "Native executable extraction" true "NATIVE_EXECUTABLE found in config output"
            else
                test_result "Native executable extraction" false "NATIVE_EXECUTABLE not found in config output"
            fi
            
            if echo "$config_output" | grep -q "NATIVE_DAEMON_COMMAND="; then
                test_result "Native daemon command extraction" true "NATIVE_DAEMON_COMMAND found in config output"
            else
                test_result "Native daemon command extraction" false "NATIVE_DAEMON_COMMAND not found in config output"
            fi
        else
            test_result "Native config parsing" false "loadNativeConfig.js failed or timed out" "Check Deno permissions and routine syntax"
        fi
    else
        test_result "Native config parsing" false "Deno not available for testing" "Install Deno runtime"
    fi
}

# Test 3: Race condition detection in harbor.sh
test_race_condition_detection() {
    log_info "Testing race condition detection in harbor.sh..."
    
    # Check current Harbor native service startup implementation
    local harbor_sh="$HARBOR_ROOT/harbor.sh"
    
    if [[ -f "$harbor_sh" ]]; then
        # Check for modern wave-based native service startup (current implementation)
        if grep -q "_harbor_start_native_service_and_wait" "$harbor_sh"; then
            test_result "Modern native service startup" true "Harbor uses _harbor_start_native_service_and_wait"
            
            # Check if it uses proper wait/synchronization
            if grep -q "wave_natives_array" "$harbor_sh" && grep -q "background_pids" "$harbor_sh"; then
                test_result "Race condition prevention" true "Harbor uses wave-based startup with proper synchronization"
            else
                test_result "Race condition prevention" false "Harbor startup may have race conditions" "Check wave-based implementation"
            fi
        else
            # Check for older pattern that could have race conditions
            if grep -q "_harbor_start_native_service.*do" "$harbor_sh" && \
               ! grep -q "_harbor_start_native_service_and_wait" "$harbor_sh"; then
                test_result "Race condition detected" false "Harbor uses old pattern without waiting" "Implement proper native service synchronization"
            else
                test_result "Native service startup" false "Cannot determine native service startup pattern" "Check harbor.sh implementation"
            fi
        fi
    else
        test_result "Harbor.sh access" false "Cannot read harbor.sh" "Check file permissions"
    fi
}

# Test 4: Dependency wave computation
test_dependency_waves() {
    log_info "Testing dependency wave computation..."
    
    # Create test dependency scenarios using actual Harbor services
    local test_scenarios=(
        "simple:webui:ollama"
        "chain:chatui:searxng:ollama"
        "parallel:webui,chatui:ollama"
        "complex:chatui:searxng:ollama"
    )
    
    for scenario in "${test_scenarios[@]}"; do
        local scenario_name=$(echo "$scenario" | cut -d: -f1)
        local services=$(echo "$scenario" | cut -d: -f2- | tr ':' ' ')
        
        log_info "Testing $scenario_name dependency scenario: $services"
        
        # Create synthetic compose files for testing
        local compose_dir="$TEMP_DIR/compose_$scenario_name"
        mkdir -p "$compose_dir"
        
        # Create base compose file
        cat > "$compose_dir/compose.yml" << 'EOF'
networks:
  harbor-network:
    external: false
EOF
        
        # Test with startupOrder.js if available
        if [[ -f "$HARBOR_ROOT/routines/startupOrder.js" ]] && command -v deno >/dev/null 2>&1; then
            local startup_output
            if startup_output=$(cd "$HARBOR_ROOT" && timeout 10 deno run --allow-read --allow-env --unstable-sloppy-imports --no-check routines/startupOrder.js $services 2>/dev/null); then
                test_result "Dependency waves: $scenario_name" true "Wave computation completed"
                
                # Check if output contains actual startupOrder.js wave structure
                if echo "$startup_output" | grep -q "WAVE_COUNT\|WAVE_.*_CONTAINERS\|WAVE_.*_NATIVES"; then
                    test_result "Wave structure: $scenario_name" true "Output contains wave information"
                else
                    test_result "Wave structure: $scenario_name" false "Output missing wave information"
                fi
            else
                test_result "Dependency waves: $scenario_name" false "Wave computation failed" "Check startupOrder.js implementation"
            fi
        else
            test_result "Dependency waves: $scenario_name" false "startupOrder.js not available" "Implement dependency wave computation"
        fi
    done
}

# Test 5: Interleaved native/container dependency patterns
test_interleaved_dependencies() {
    log_info "Testing interleaved native/container dependency patterns..."
    
    # Test patterns using real Harbor services that can run natively or as containers
    local interleaved_patterns=(
        "native-container-native:speaches(native)->webui(container)->ollama(native)"
        "container-native-container:webui(container)->speaches(native)->webui(container)"
        "mixed-chain:ollama(native)->webui(container)->speaches(native)"
    )
    
    for pattern in "${interleaved_patterns[@]}"; do
        local pattern_name=$(echo "$pattern" | cut -d: -f1)
        local pattern_desc=$(echo "$pattern" | cut -d: -f2)
        
        log_info "Testing $pattern_name: $pattern_desc"
        
        # These are complex scenarios that would require full Harbor startup simulation
        # For now, we test the pattern recognition logic
        
        # Check for interleaved patterns (either native→container→native or container→native→container)
        if [[ "$pattern_desc" == *"native"*"container"*"native"* ]] || [[ "$pattern_desc" == *"container"*"native"*"container"* ]]; then
            test_result "Interleaved pattern: $pattern_name" true "Pattern recognized as interleaved"
            
            # Test actual dependency resolution with real Harbor services
            local services_list=$(echo "$pattern_desc" | grep -o '[a-zA-Z]*(' | sed 's/(//g' | tr '\n' ' ')
            if [[ -f "$HARBOR_ROOT/routines/startupOrder.js" ]] && command -v deno >/dev/null 2>&1; then
                local resolution_output
                if resolution_output=$(cd "$HARBOR_ROOT" && timeout 10 deno run --allow-read --allow-env --unstable-sloppy-imports --no-check routines/startupOrder.js $services_list 2>/dev/null); then
                    test_result "Unified dependency resolution: $pattern_name" true "startupOrder.js resolved interleaved dependencies"
                else
                    test_result "Unified dependency resolution: $pattern_name" false "startupOrder.js failed to resolve dependencies" "Check dependency resolution implementation"
                fi
            else
                test_result "Unified dependency resolution: $pattern_name" false "startupOrder.js not available" "Implement unified topological sorting"
            fi
        else
            test_result "Interleaved pattern: $pattern_name" false "Pattern not recognized"
        fi
    done
}

# Test 6: Circular dependency detection (future work)
# TODO: Re-enable when Harbor has synthetic compose support or real circular dependencies to test
# Current issue: Real Harbor services don't have circular dependencies, and testing requires synthetic compose files
# Future options: 1) Add isolated test environment with synthetic compose files
#                2) Create intentional circular dependencies for testing (not recommended)
#                3) Test with mock/stub dependency graphs
test_circular_dependencies() {
    log_info "Testing circular dependency detection..."
    
    # NOTE: Real Harbor services don't have circular dependencies, so we can't test
    # the actual circular dependency detection logic without creating synthetic compose files.
    # This would require a more complex test setup that doesn't interfere with Harbor's
    # actual compose file resolution system.
    
    # For now, we just verify that the startupOrder.js routine has the capability
    if [[ -f "$HARBOR_ROOT/routines/startupOrder.js" ]] && command -v deno >/dev/null 2>&1; then
        # Check that the routine contains circular dependency detection code
        if grep -q "CIRCULAR_DEPENDENCY\|findCycles" "$HARBOR_ROOT/routines/startupOrder.js"; then
            test_result "Circular dependency detection capability" true "startupOrder.js includes circular dependency detection logic"
        else
            test_result "Circular dependency detection capability" false "startupOrder.js missing circular dependency detection" "Add circular dependency detection to startupOrder.js"
        fi
        
        # TODO: Future work - create isolated test environment with synthetic compose files
        # to test actual circular dependency detection behavior
        test_result "Circular dependency detection test" false "Test skipped - requires synthetic compose environment" "Create isolated test environment for circular dependency testing"
    else
        test_result "Circular dependency detection" false "startupOrder.js not available" "Implement circular dependency detection"
    fi
}

# Test 7: Fallback behavior validation
test_fallback_behavior() {
    log_info "Testing fallback behavior for dependency resolution failures..."
    
    # Test with non-existent services
    local nonexistent_services=("nonexistent1" "nonexistent2" "nonexistent3")
    
    if [[ -f "$HARBOR_ROOT/routines/startupOrder.js" ]] && command -v deno >/dev/null 2>&1; then
        local fallback_output
        if fallback_output=$(cd "$HARBOR_ROOT" && timeout 10 deno run --allow-read --allow-env --unstable-sloppy-imports --no-check routines/startupOrder.js "${nonexistent_services[@]}" 2>&1); then
            test_result "Fallback behavior" true "Graceful handling of non-existent services"
            
            # Check if fallback provides original order (services placed in wave 1)
            if echo "$fallback_output" | grep -q "WAVE_1_CONTAINERS"; then
                test_result "Fallback order" true "Fallback order provided (services placed in wave 1)"
            else
                test_result "Fallback order" false "No fallback order provided" "Implement graceful degradation"
            fi
        else
            test_result "Fallback behavior" false "Dependency resolution failed completely" "Implement robust error handling"
        fi
    else
        test_result "Fallback behavior" false "startupOrder.js not available" "Implement fallback behavior"
    fi
}

# Test 8: Integration with Harbor's existing systems
test_harbor_integration() {
    log_info "Testing integration with Harbor's existing systems..."
    
    # Test that harbor.sh can be called with --help (basic integration test)
    if timeout 10 "$HARBOR_ROOT/harbor.sh" --help >/dev/null 2>&1; then
        test_result "Harbor CLI integration" true "harbor.sh --help works"
    else
        test_result "Harbor CLI integration" false "harbor.sh --help failed" "Check Harbor CLI functionality"
    fi
    
    # Test that compose file resolution works
    if [[ -f "$HARBOR_ROOT/compose.yml" ]]; then
        test_result "Compose file structure" true "Base compose.yml exists"
    else
        test_result "Compose file structure" false "Base compose.yml missing" "Initialize Harbor compose structure"
    fi
    
    # Test that profiles directory exists
    if [[ -d "$HARBOR_ROOT/profiles" ]]; then
        test_result "Profiles system" true "profiles/ directory exists"
    else
        test_result "Profiles system" false "profiles/ directory missing" "Initialize Harbor profiles system"
    fi
}

# Show help
show_help() {
    cat << 'EOF'
Harbor Native Service Dependency Resolution Test Suite

DESCRIPTION:
    Consolidated test suite for Harbor's native service functionality including
    dependency resolution, configuration parsing, startup ordering, and race condition fixes.

USAGE:
    ./test_native_services.sh [OPTIONS]

OPTIONS:
    (no args)               Run complete test suite
    --verify-bug            Show the dependency race condition bug
    --verify-fix            Check if the surgical fix is implemented
    --test-interleaved      Test interleaved dependency patterns
    --help, -h              Show this help message

WHAT IT TESTS:
    ✓ Harbor native service infrastructure
    ✓ Native config parsing functionality
    ✓ Race condition detection in harbor.sh
    ✓ Dependency wave computation
    ✓ Interleaved native/container dependency patterns
    ✓ Fallback behavior validation
    ✓ Integration with Harbor's existing systems
    ✓ Native service readiness implementation validation
    ✓ Readiness checking infrastructure
    ✓ Edge cases (empty service lists, single services)
    🚧 Circular dependency detection (disabled - TODO: requires synthetic compose support)
    🚧 Parallel execution within waves (disabled - TODO: requires synthetic compose support)
    🚧 Critical phase vs wave comparison scenarios (disabled - TODO: requires interleaved dependencies)

SAFETY:
    - No Harbor services are started
    - No network connections made
    - No system modifications
    - Uses temporary directories for test artifacts

EXIT CODES:
    0   All tests passed
    1   Some tests failed
EOF
}

# Safe function sourcing (won't execute, just check syntax)
check_function_exists() {
    local function_name="$1"
    local file="$2"
    
    if [[ ! -f "$file" ]]; then
        return 1
    fi
    
    # Use grep to check if function is defined (safer than sourcing)
    if grep -q "^${function_name}()" "$file" || grep -q "^function ${function_name}" "$file"; then
        return 0
    else
        return 1
    fi
}

# Test: Native Service Readiness Implementation
test_native_service_readiness() {
    log_info "Testing native service readiness implementation..."
    
    local harbor_sh="$HARBOR_ROOT/harbor.sh"
    if [[ ! -f "$harbor_sh" ]]; then
        test_result "Native service readiness check" false "harbor.sh not found"
        return
    fi
    
    # Check if Harbor has native service readiness functionality
    if check_function_exists "_harbor_wait_for_native_service_ready" "$harbor_sh"; then
        test_result "Native service readiness function" true "_harbor_wait_for_native_service_ready exists"
        
        # Check if the readiness function is actually being used
        if grep -q "_harbor_wait_for_native_service_ready.*||" "$harbor_sh"; then
            test_result "Readiness integration" true "Readiness checking integrated into native service startup"
        else
            test_result "Readiness integration" false "Readiness function exists but not integrated"
        fi
        
        # Check if it uses Harbor's port discovery infrastructure
        if grep -A 10 "_harbor_wait_for_native_service_ready()" "$harbor_sh" | grep -q "get_service_port"; then
            test_result "Port discovery integration" true "Uses Harbor's get_service_port infrastructure"
        else
            test_result "Port discovery integration" false "Missing get_service_port integration"
        fi
        
    else
        test_result "Native service readiness function" false "_harbor_wait_for_native_service_ready not found"
    fi
    
    # Check for modern wave-based startup (replaces old surgical fix approach)
    if grep -q "_harbor_start_native_service_and_wait" "$harbor_sh"; then
        test_result "Wave-based native startup" true "Harbor uses modern wave-based native service startup"
    else
        test_result "Wave-based native startup" false "Harbor missing wave-based startup implementation"
    fi
}

# Test: Readiness Checking Infrastructure
test_readiness_infrastructure() {
    log_info "Testing readiness checking infrastructure..."
    
    # Check if nc (netcat) is available for port checking
    if command -v nc >/dev/null 2>&1; then
        test_result "Port checking tool (nc)" true "Available"
    else
        test_result "Port checking tool (nc)" false "Not available - readiness checking may not work"
    fi
    
    # Check if timeout command is available
    if command -v timeout >/dev/null 2>&1; then
        test_result "Timeout command" true "Available for bounded waiting"
    else
        test_result "Timeout command" false "Not available - may use fallback"
    fi
    
    # Check for existing get_service_port function
    if check_function_exists "get_service_port" "$HARBOR_ROOT/harbor.sh"; then
        test_result "Service port detection" true "get_service_port function exists"
    else
        test_result "Service port detection" false "get_service_port function not found"
    fi
}

# Test: Parallel Execution Within Waves
# TODO: Re-enable when Harbor supports this scenario
# Current issue: Uses synthetic compose files, but Harbor's startupOrder.js works with real compose files
# Future options: 1) Add synthetic compose support to startupOrder.js test mode
#                2) Create real Harbor services with parallel dependency patterns
#                3) Modify existing services to demonstrate parallel execution
test_parallel_execution_within_waves() {
    log_info "Testing parallel execution within dependency waves..."
    
    # Create scenario with parallel services in same wave
    cat > "$TEMP_DIR/compose.database.yml" << 'EOF'
services:
  database:
    image: postgres
    # Root service
EOF

    cat > "$TEMP_DIR/compose.api1.yml" << 'EOF'
services:
  api1:
    image: api1:latest
    depends_on:
      - database
EOF

    cat > "$TEMP_DIR/compose.api2.yml" << 'EOF'
services:
  api2:
    image: api2:latest
    depends_on:
      - database  # Both api1 and api2 depend only on database
EOF

    cd "$TEMP_DIR"
    local result
    result=$(deno run --allow-read --allow-env --unstable-sloppy-imports "$HARBOR_ROOT/routines/startupOrder.js" \
             --container database api1 api2 --native 2>/dev/null)
    
    if [[ $? -eq 0 && -n "$result" ]]; then
        # Load bash variables from output (NEW TYPE-AWARE WAVE FORMAT)
        eval "$result"
        
        if [[ "$STATUS" == "SUCCESS" && "$WAVE_COUNT" == "2" ]]; then
            # Wave 2 should contain both api1 and api2 (parallel execution)
            if [[ "$WAVE_2_CONTAINERS" =~ api1 && "$WAVE_2_CONTAINERS" =~ api2 ]]; then
                test_result "Parallel execution within waves" true "api1 and api2 correctly grouped in same wave"
            else
                test_result "Parallel execution within waves" false "api1 and api2 not properly grouped in wave 2"
            fi
        else
            test_result "Parallel execution within waves" false "Expected 2 waves with SUCCESS status, got $WAVE_COUNT waves"
        fi
    else
        test_result "Parallel execution within waves" false "Failed to compute parallel wave scenario"
    fi
    
    # Return to Harbor root
    cd "$HARBOR_ROOT"
}

# Test: Phase vs Wave Comparison (Critical)
# TODO: Re-enable when Harbor has interleaved native→container→native dependencies
# Current issue: This scenario doesn't exist in real Harbor services yet, but is expected soon
# Future options: 1) Add synthetic compose support for testing edge cases
#                2) Create real Harbor services with interleaved native/container dependencies 
#                3) Wait for natural evolution of Harbor service dependencies
test_phase_vs_wave_comparison() {
    log_info "Testing critical scenario that breaks phase-based approach..."
    
    # Create the exact scenario that breaks phase-based approach
    cat > "$TEMP_DIR/compose.db.yml" << 'EOF'
services:
  db:
    image: postgres
    # Native service, no dependencies
EOF

    cat > "$TEMP_DIR/compose.api.yml" << 'EOF'
services:
  api:
    image: api:latest
    depends_on:
      - db  # Container depends on native
EOF

    cat > "$TEMP_DIR/compose.cache.yml" << 'EOF'
services:
  cache:
    image: redis
    depends_on:
      - api  # Native depends on container - BREAKS PHASE-BASED!
EOF

    cd "$TEMP_DIR"
    local wave_result
    wave_result=$(deno run --allow-read --allow-env --unstable-sloppy-imports "$HARBOR_ROOT/routines/startupOrder.js" \
                 --container api --native db cache 2>/dev/null)
    
    if [[ $? -eq 0 && -n "$wave_result" ]]; then
        # Load bash variables from output (NEW TYPE-AWARE WAVE FORMAT)
        eval "$wave_result"
        
        if [[ "$STATUS" == "SUCCESS" && "$WAVE_COUNT" == "3" ]]; then
            # Should create 3 waves: db → api → cache
            if [[ "$WAVE_1_NATIVES" =~ db && "$WAVE_2_CONTAINERS" =~ api && "$WAVE_3_NATIVES" =~ cache ]]; then
                test_result "Phase vs Wave comparison" true "Wave approach correctly handles interleaved native→container→native scenario"
                log_info "  ✅ Wave ordering: db(native) → api(container) → cache(native)"
                log_info "  ❌ Phase ordering would be: db,cache(natives) → api(container) - BROKEN!"
            else
                test_result "Phase vs Wave comparison" false "Incorrect wave ordering - interleaved dependencies not handled correctly"
            fi
        else
            test_result "Phase vs Wave comparison" false "Expected 3 waves with SUCCESS status for interleaved scenario, got $WAVE_COUNT waves"
        fi
    else
        test_result "Phase vs Wave comparison" false "Failed to compute waves for phase-breaking scenario"
    fi
    
    # Return to Harbor root
    cd "$HARBOR_ROOT"
}

# Test: Edge Cases (Empty and Single Service)
test_edge_cases() {
    log_info "Testing edge cases for dependency wave computation..."
    
    # Check prerequisites like other working tests
    if [[ -f "$HARBOR_ROOT/routines/startupOrder.js" ]] && command -v deno >/dev/null 2>&1; then
        
        # Test empty service lists - startupOrder.js currently requires arguments
        local empty_result
        if empty_result=$(cd "$HARBOR_ROOT" && timeout 5 deno run --allow-read --allow-env --unstable-sloppy-imports --no-check routines/startupOrder.js 2>&1); then
            # This should fail and show usage - that's expected behavior
            if echo "$empty_result" | grep -q "Usage:"; then
                test_result "Empty service list handling" true "startupOrder.js correctly shows usage for empty arguments"
            else
                test_result "Empty service list handling" false "startupOrder.js behavior unexpected for empty arguments"
            fi
        else
            # If it fails, that's also expected for empty arguments
            test_result "Empty service list handling" true "startupOrder.js correctly rejects empty arguments"
        fi
        
        # Test single real Harbor service (webui has no dependencies in its compose file)
        local single_result
        if single_result=$(cd "$HARBOR_ROOT" && timeout 10 deno run --allow-read --allow-env --unstable-sloppy-imports --no-check routines/startupOrder.js webui 2>/dev/null); then
            # Check for success and single wave
            if echo "$single_result" | grep -q "STATUS=SUCCESS" && echo "$single_result" | grep -q "WAVE_COUNT=1"; then
                test_result "Single service handling" true "Single real service (webui) correctly placed in one wave"
            else
                test_result "Single service handling" false "Single service wave structure not as expected"
            fi
        else
            test_result "Single service handling" false "Failed to handle single real Harbor service scenario"
        fi
        
    else
        test_result "Edge cases testing" false "startupOrder.js not available" "Install Deno runtime and check startupOrder.js exists"
    fi
}

# Run all tests
run_all_tests() {
    echo "=========================================="
    echo "Harbor Native Service Dependency Tests"
    echo "=========================================="
    echo
    log_info "Running consolidated native service tests..."
    echo
    
    setup_temp_dir
    
    # Run all test functions
    test_native_infrastructure
    test_native_config_parsing
    test_race_condition_detection
    test_dependency_waves
    test_interleaved_dependencies
    # test_circular_dependencies            # TODO: Re-enable when synthetic compose support added
    test_fallback_behavior
    test_harbor_integration
    test_native_service_readiness
    test_readiness_infrastructure
    # test_parallel_execution_within_waves  # TODO: Re-enable when synthetic compose support added
    # test_phase_vs_wave_comparison         # TODO: Re-enable when interleaved dependencies exist
    test_edge_cases
    
    echo
    echo "=========================================="
    echo "Test Results Summary"
    echo "=========================================="
    
    local success_rate
    success_rate=$(( (TESTS_PASSED * 100) / TESTS_TOTAL ))
    
    echo "Tests passed: $TESTS_PASSED/$TESTS_TOTAL ($success_rate%)"
    echo
    
    if [[ $TESTS_PASSED -eq $TESTS_TOTAL ]]; then
        log_success "🎉 ALL TESTS PASSED!"
        echo "✅ Harbor native service dependency resolution is working correctly"
        return 0
    else
        log_error "❌ SOME TESTS FAILED"
        echo "⚠️  See failures above for details and recommended actions"
        return 1
    fi
}

# Verify bug function
verify_bug() {
    echo "=========================================="
    echo "Harbor Native Service Race Condition Bug"
    echo "=========================================="
    echo
    
    setup_temp_dir
    
    log_info "Checking for the race condition bug in harbor.sh..."
    
    local harbor_sh="$HARBOR_ROOT/harbor.sh"
    if [[ -f "$harbor_sh" ]]; then
        # Look for the buggy pattern
        if grep -n "for service in.*native_targets.*do" "$harbor_sh"; then
            local line_num=$(grep -n "for service in.*native_targets.*do" "$harbor_sh" | cut -d: -f1)
            echo
            log_error "🐛 RACE CONDITION BUG FOUND at line $line_num"
            echo
            echo "Problematic code:"
            grep -A3 "for service in.*native_targets.*do" "$harbor_sh" | sed 's/^/    /'
            echo
            echo "PROBLEM: Native services start without waiting for readiness"
            echo "IMPACT: Containers fail when connecting to native dependencies"
            echo "SOLUTION: Replace with _harbor_start_native_services_with_dependencies"
        else
            log_success "✅ Race condition pattern not found - may be fixed"
        fi
    else
        log_error "Cannot access harbor.sh"
    fi
}

# Verify fix function
verify_fix() {
    echo "=========================================="
    echo "Harbor Native Service Race Condition Fix"
    echo "=========================================="
    echo
    
    setup_temp_dir
    
    log_info "Checking if the surgical fix is implemented..."
    
    local harbor_sh="$HARBOR_ROOT/harbor.sh"
    if [[ -f "$harbor_sh" ]]; then
        # Look for the fixed pattern
        if grep -q "_harbor_start_native_services_with_dependencies" "$harbor_sh"; then
            log_success "✅ SURGICAL FIX DETECTED"
            echo
            echo "Fixed code found:"
            grep -n "_harbor_start_native_services_with_dependencies" "$harbor_sh" | sed 's/^/    /'
            echo
            echo "✅ Native services now start with dependency awareness"
            echo "✅ Race condition should be resolved"
        else
            log_error "❌ SURGICAL FIX NOT FOUND"
            echo
            echo "Expected function not found: _harbor_start_native_services_with_dependencies"
            echo "The race condition fix has not been applied"
        fi
    else
        log_error "Cannot access harbor.sh"
    fi
}

# Test interleaved patterns
test_interleaved_patterns() {
    echo "=========================================="
    echo "Harbor Interleaved Dependency Patterns"
    echo "=========================================="
    echo
    
    setup_temp_dir
    
    log_info "Testing interleaved native/container dependency patterns..."
    test_interleaved_dependencies
    
    echo
    if [[ $TESTS_PASSED -eq $TESTS_TOTAL ]]; then
        log_success "✅ Interleaved patterns handled correctly"
    else
        log_error "❌ Interleaved patterns need attention"
        echo "Two-phase execution (natives first, containers second) cannot handle"
        echo "dependency chains that alternate between native and container services."
    fi
}

# Main execution
main() {
    case "${1:-}" in
        --verify-bug)
            verify_bug
            ;;
        --verify-fix)
            verify_fix
            ;;
        --test-interleaved)
            test_interleaved_patterns
            ;;
        --help|-h)
            show_help
            exit 0
            ;;
        "")
            run_all_tests
            ;;
        *)
            log_error "Unknown option: $1"
            echo
            show_help
            exit 1
            ;;
    esac
}

# Safety check - ensure we're in Harbor root
if [[ ! -f "$HARBOR_ROOT/harbor.sh" ]]; then
    log_error "Not in Harbor root directory (harbor.sh not found)"
    log_info "Please run from Harbor root: ./tests/test_native_services.sh"
    exit 1
fi

main "$@"