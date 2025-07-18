#!/bin/bash
#
# Harbor Core Infrastructure Test Suite
#
# Tests basic Harbor functionality including CLI, routines, configurations,
# and core infrastructure without starting any services.
#
# SAFE: No service startup, no network operations, no system modifications
# FOCUSED: Core Harbor functionality validation
#
# Usage:
#   ./test_harbor_core.sh                    # Run all tests
#   ./test_harbor_core.sh --help             # Show help

set -euo pipefail

# Test configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HARBOR_ROOT="$(dirname "$SCRIPT_DIR")"
TESTS_PASSED=0
TESTS_TOTAL=0

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

# Test result tracking
test_result() {
    local test_name="$1"
    local passed="$2"
    local message="${3:-}"
    
    ((TESTS_TOTAL++))
    
    if [[ "$passed" == "true" ]]; then
        ((TESTS_PASSED++))
        log_success "$test_name${message:+ - $message}"
    else
        log_error "$test_name${message:+ - $message}"
    fi
}

# Test 1: Harbor executable and basic functionality
test_harbor_executable() {
    log_info "Testing Harbor executable..."
    
    # Check harbor.sh exists and is executable
    if [[ -x "$HARBOR_ROOT/harbor.sh" ]]; then
        test_result "Harbor executable" true "harbor.sh found and executable"
    else
        test_result "Harbor executable" false "harbor.sh not found or not executable"
        return
    fi
    
    # Test harbor --help (safe command)
    if timeout 10 "$HARBOR_ROOT/harbor.sh" --help >/dev/null 2>&1; then
        test_result "Harbor help command" true "harbor.sh --help works"
    else
        test_result "Harbor help command" false "harbor.sh --help failed or timed out"
    fi
}

# Test 2: Routines directory and key files
test_routines_infrastructure() {
    log_info "Testing routines infrastructure..."
    
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
    )
    
    for routine in "${key_routines[@]}"; do
        if [[ -f "$HARBOR_ROOT/routines/$routine" ]]; then
            test_result "Routine: $routine" true "Found"
        else
            test_result "Routine: $routine" false "Missing"
        fi
    done
    
    # Test Deno availability for routine execution
    if command -v deno >/dev/null 2>&1; then
        test_result "Deno runtime" true "Available for routine execution"
    else
        test_result "Deno runtime" false "Not available - routines cannot be tested"
    fi
}

# Test 3: Native service configurations
test_native_configurations() {
    log_info "Testing native service configurations..."
    
    # Find all *_native.yml files
    local native_configs=()
    while IFS= read -r -d '' file; do
        native_configs+=("$file")
    done < <(find "$HARBOR_ROOT" -name "*_native.yml" -type f -print0 2>/dev/null || true)
    
    if [[ ${#native_configs[@]} -eq 0 ]]; then
        test_result "Native configurations" false "No *_native.yml files found"
        return
    fi
    
    test_result "Native configurations" true "Found ${#native_configs[@]} native config files"
    
    # Test specific known configurations
    local known_configs=(
        "ollama/ollama_native.yml"
        "speaches/speaches_native.yml"
    )
    
    for config in "${known_configs[@]}"; do
        if [[ -f "$HARBOR_ROOT/$config" ]]; then
            test_result "Config: $(basename "$config")" true "Present"
        else
            test_result "Config: $(basename "$config")" false "Missing (optional)"
        fi
    done
}

# Test 4: Compose file structure
test_compose_structure() {
    log_info "Testing compose file structure..."
    
    # Check for base compose file
    if [[ -f "$HARBOR_ROOT/compose.yml" ]]; then
        test_result "Base compose file" true "compose.yml exists"
    else
        test_result "Base compose file" false "compose.yml not found"
    fi
    
    # Count compose files
    local compose_files=()
    while IFS= read -r -d '' file; do
        compose_files+=("$file")
    done < <(find "$HARBOR_ROOT" -name "compose.*.yml" -type f -print0 2>/dev/null || true)
    
    if [[ ${#compose_files[@]} -gt 0 ]]; then
        test_result "Service compose files" true "Found ${#compose_files[@]} compose files"
    else
        test_result "Service compose files" false "No compose.*.yml files found"
    fi
    
    # Check for cross-service files
    local cross_service_files=()
    while IFS= read -r -d '' file; do
        cross_service_files+=("$file")
    done < <(find "$HARBOR_ROOT" -name "compose.x.*.yml" -type f -print0 2>/dev/null || true)
    
    if [[ ${#cross_service_files[@]} -gt 0 ]]; then
        test_result "Cross-service files" true "Found ${#cross_service_files[@]} cross-service files"
    else
        test_result "Cross-service files" false "No compose.x.*.yml files found"
    fi
}

# Test 5: Environment and configuration system
test_environment_system() {
    log_info "Testing environment and configuration system..."
    
    # Check for profiles directory
    if [[ -d "$HARBOR_ROOT/profiles" ]]; then
        test_result "Profiles directory" true "profiles/ directory exists"
    else
        test_result "Profiles directory" false "profiles/ directory not found"
    fi
    
    # Check for default environment file
    if [[ -f "$HARBOR_ROOT/profiles/default.env" ]]; then
        test_result "Default environment" true "profiles/default.env exists"
    else
        test_result "Default environment" false "profiles/default.env not found"
    fi
    
    # Check for app backend structure (for native service data)
    if [[ -d "$HARBOR_ROOT/app/backend" ]]; then
        test_result "App backend structure" true "app/backend/ directory exists"
    else
        test_result "App backend structure" false "app/backend/ directory not found"
    fi
}

# Test 6: Documentation structure
test_documentation() {
    log_info "Testing documentation structure..."
    
    # Check for docs directory
    if [[ -d "$HARBOR_ROOT/docs" ]]; then
        test_result "Documentation directory" true "docs/ directory exists"
    else
        test_result "Documentation directory" false "docs/ directory not found"
    fi
    
    # Check for key documentation files
    local key_docs=(
        "README.md"
        "CLAUDE.md"
    )
    
    for doc in "${key_docs[@]}"; do
        if [[ -f "$HARBOR_ROOT/$doc" ]]; then
            test_result "Documentation: $doc" true "Present"
        else
            test_result "Documentation: $doc" false "Missing"
        fi
    done
}

# Test 7: System dependencies
test_system_dependencies() {
    log_info "Testing system dependencies..."
    
    # Check for Docker
    if command -v docker >/dev/null 2>&1; then
        test_result "Docker" true "Available"
    else
        test_result "Docker" false "Not available - Harbor requires Docker"
    fi
    
    # Check for Docker Compose
    if command -v docker-compose >/dev/null 2>&1; then
        test_result "Docker Compose" true "Available"
    else
        test_result "Docker Compose" false "Not available - Harbor requires Docker Compose"
    fi
    
    # Check for jq (used in Harbor scripts)
    if command -v jq >/dev/null 2>&1; then
        test_result "jq" true "Available"
    else
        test_result "jq" false "Not available - some Harbor features may not work"
    fi
    
    # Check for nc (netcat) for port checking
    if command -v nc >/dev/null 2>&1; then
        test_result "netcat (nc)" true "Available for port checking"
    else
        test_result "netcat (nc)" false "Not available - readiness checking may not work"
    fi
}

# Main test execution
run_all_tests() {
    echo "=================================="
    echo "Harbor Core Infrastructure Tests"
    echo "=================================="
    echo
    log_info "Testing Harbor core functionality (no services started)..."
    echo
    
    # Run all test functions
    test_harbor_executable
    test_routines_infrastructure
    test_native_configurations
    test_compose_structure
    test_environment_system
    test_documentation
    test_system_dependencies
    
    echo
    echo "=================================="
    echo "Test Results Summary"
    echo "=================================="
    
    local success_rate
    success_rate=$(( (TESTS_PASSED * 100) / TESTS_TOTAL ))
    
    echo "Tests passed: $TESTS_PASSED/$TESTS_TOTAL ($success_rate%)"
    echo
    
    if [[ $TESTS_PASSED -eq $TESTS_TOTAL ]]; then
        log_success "🎉 ALL TESTS PASSED!"
        echo "✅ Harbor core infrastructure is ready"
        return 0
    else
        log_error "❌ SOME TESTS FAILED"
        echo "⚠️  See failures above for details"
        return 1
    fi
}

# Help function
show_help() {
    cat << 'EOF'
Harbor Core Infrastructure Test Suite

DESCRIPTION:
    Tests basic Harbor functionality including CLI, routines, configurations,
    and core infrastructure without starting any services.

USAGE:
    ./test_harbor_core.sh [OPTIONS]

OPTIONS:
    (no args)           Run complete test suite
    --help, -h          Show this help message

WHAT IT TESTS:
    ✓ Harbor executable and basic functionality
    ✓ Routines infrastructure (loadNativeConfig.js, docker.js, etc.)
    ✓ Native service configurations (*_native.yml files)
    ✓ Compose file structure (compose.yml, compose.*.yml)
    ✓ Environment and configuration system
    ✓ Documentation structure
    ✓ System dependencies (Docker, jq, nc, etc.)

SAFETY:
    - No Harbor services are started
    - No network connections made
    - No system modifications
    - Only reads existing files and checks commands

EXIT CODES:
    0   All tests passed
    1   Some tests failed
EOF
}

# Main execution
main() {
    case "${1:-}" in
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
    log_info "Please run from Harbor root: ./tests/test_harbor_core.sh"
    exit 1
fi

main "$@"