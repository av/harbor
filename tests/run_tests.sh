#!/bin/bash
#
# Harbor Unified Test Runner
#
# Runs all Harbor tests in the correct order and provides comprehensive
# reporting. Supports both shell-based tests and Deno-based routine tests.
#
# Usage:
#   ./run_tests.sh                    # Run all tests
#   ./run_tests.sh --core             # Run only core infrastructure tests
#   ./run_tests.sh --native           # Run only native service tests
#   ./run_tests.sh --integration      # Run only integration tests
#   ./run_tests.sh --routines         # Run only Deno routine tests
#   ./run_tests.sh --fast             # Run core + native + routines (no integration)
#   ./run_tests.sh --help             # Show help

set -euo pipefail

# Test configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HARBOR_ROOT="$(dirname "$SCRIPT_DIR")"
START_TIME=$(date +%s)

# Test categories
RUN_CORE=true
RUN_NATIVE=true
RUN_INTEGRATION=true
RUN_ROUTINES=true

# Results tracking (bash 3 compatible)
TEST_RESULTS=""
TEST_TIMES=""
TOTAL_TESTS=0
TOTAL_PASSED=0
OVERALL_SUCCESS=true

# Colors for output
if [[ -t 1 ]]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    BOLD='\033[1m'
    NC='\033[0m'
else
    RED='' GREEN='' YELLOW='' BLUE='' BOLD='' NC=''
fi

# Logging functions
log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $*"; }
log_header() { echo -e "${BOLD}${BLUE}$*${NC}"; }

# Parse command line arguments
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --core)
                RUN_CORE=true
                RUN_NATIVE=false
                RUN_INTEGRATION=false
                RUN_ROUTINES=false
                shift
                ;;
            --native)
                RUN_CORE=false
                RUN_NATIVE=true
                RUN_INTEGRATION=false
                RUN_ROUTINES=false
                shift
                ;;
            --integration)
                RUN_CORE=false
                RUN_NATIVE=false
                RUN_INTEGRATION=true
                RUN_ROUTINES=false
                shift
                ;;
            --routines)
                RUN_CORE=false
                RUN_NATIVE=false
                RUN_INTEGRATION=false
                RUN_ROUTINES=true
                shift
                ;;
            --fast)
                RUN_CORE=true
                RUN_NATIVE=true
                RUN_INTEGRATION=false
                RUN_ROUTINES=true
                shift
                ;;
            --help|-h)
                show_help
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                show_help
                exit 1
                ;;
        esac
    done
}

# Show help
show_help() {
    cat << 'EOF'
Harbor Unified Test Runner

DESCRIPTION:
    Runs all Harbor tests in the correct order and provides comprehensive
    reporting. Supports both shell-based tests and Deno-based routine tests.

USAGE:
    ./run_tests.sh [OPTIONS]

OPTIONS:
    (no args)        Run all tests (core + native + routines + integration)
    --core           Run only core infrastructure tests
    --native         Run only native service tests
    --integration    Run only integration tests (starts real services)
    --routines       Run only Deno routine tests
    --fast           Run fast tests only (core + native + routines, no integration)
    --help, -h       Show this help message

TEST CATEGORIES:
    Core Infrastructure    - Basic Harbor functionality (fast, safe)
    Native Services       - Dependency resolution logic (fast, safe)
    Routine Tests         - Deno unit tests (fast, safe)
    Integration Tests     - Real service startup (slow, starts services)

REQUIREMENTS:
    - Harbor must be properly installed
    - Docker must be running (for integration tests)
    - Deno must be installed (for routine tests)
    - System tools: jq, nc, curl

EXIT CODES:
    0   All tests passed
    1   Some tests failed
    2   Test execution error
EOF
}

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."
    
    # Check Harbor installation
    if [[ ! -f "$HARBOR_ROOT/harbor.sh" ]]; then
        log_error "Harbor installation not found (harbor.sh missing)"
        log_error "Please run from Harbor root directory"
        exit 2
    fi
    
    # Check Docker (required for integration tests)
    if [[ "$RUN_INTEGRATION" == "true" ]]; then
        if ! command -v docker >/dev/null 2>&1; then
            log_error "Docker is required for integration tests"
            log_error "Either install Docker or run with --fast to skip integration tests"
            exit 2
        fi
        
        if ! docker ps >/dev/null 2>&1; then
            log_error "Docker is not running"
            log_error "Please start Docker daemon or run with --fast to skip integration tests"
            exit 2
        fi
    fi
    
    # Check Deno (required for routine tests)
    if [[ "$RUN_ROUTINES" == "true" ]]; then
        if ! command -v deno >/dev/null 2>&1; then
            log_warning "Deno is not installed, skipping routine tests"
            RUN_ROUTINES=false
        fi
    fi
    
    # Check system tools
    local missing_tools=()
    for tool in jq nc curl; do
        if ! command -v "$tool" >/dev/null 2>&1; then
            missing_tools+=("$tool")
        fi
    done
    
    if [[ ${#missing_tools[@]} -gt 0 ]]; then
        log_warning "Missing system tools: ${missing_tools[*]}"
        log_warning "Some tests may fail or be skipped"
    fi
    
    log_success "Prerequisites check completed"
}

# Run a test suite and capture results
run_test_suite() {
    local test_name="$1"
    local test_command="$2"
    local test_description="$3"
    
    log_header "═══════════════════════════════════════════════════════════"
    log_header "Running $test_name"
    log_header "═══════════════════════════════════════════════════════════"
    log_info "$test_description"
    echo
    
    local start_time=$(date +%s)
    local exit_code=0
    
    # Run the test and capture output
    if eval "$test_command"; then
        TEST_RESULTS="${TEST_RESULTS}${test_name}:PASSED;"
        log_success "$test_name completed successfully"
    else
        exit_code=$?
        TEST_RESULTS="${TEST_RESULTS}${test_name}:FAILED;"
        OVERALL_SUCCESS=false
        log_error "$test_name failed with exit code $exit_code"
    fi
    
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    TEST_TIMES="${TEST_TIMES}${test_name}:${duration};"
    
    echo
    log_info "$test_name completed in ${duration}s"
    echo
    
    return $exit_code
}

# Run core infrastructure tests
run_core_tests() {
    if [[ "$RUN_CORE" == "true" ]]; then
        run_test_suite \
            "Core Infrastructure Tests" \
            "\"$SCRIPT_DIR/test_harbor_core.sh\"" \
            "Testing basic Harbor functionality without starting services"
    fi
}

# Run native service tests
run_native_tests() {
    if [[ "$RUN_NATIVE" == "true" ]]; then
        run_test_suite \
            "Native Service Tests" \
            "\"$SCRIPT_DIR/test_native_services.sh\"" \
            "Testing native service dependency resolution and orchestration"
    fi
}

# Run Deno routine tests
run_routine_tests() {
    if [[ "$RUN_ROUTINES" == "true" ]]; then
        run_test_suite \
            "Routine Tests" \
            "cd \"$HARBOR_ROOT\" && deno test --allow-read --allow-env --unstable-sloppy-imports --no-check routines/tests/test_startup_computation.js routines/tests/test_dependency_extraction.js" \
            "Testing Harbor TypeScript/JavaScript routines"
    fi
}

# Run integration tests
run_integration_tests() {
    if [[ "$RUN_INTEGRATION" == "true" ]]; then
        run_test_suite \
            "Integration Tests" \
            "\"$SCRIPT_DIR/test_native_integration.sh\"" \
            "End-to-end testing with actual Harbor services (starts real services)"
    fi
}

# Extract test statistics from shell test output
extract_shell_stats() {
    local test_name="$1"
    local output="$2"
    
    # Look for "Tests passed: X/Y" pattern
    if echo "$output" | grep -q "Tests passed:"; then
        local stats=$(echo "$output" | grep "Tests passed:" | tail -1)
        local passed=$(echo "$stats" | sed 's/.*Tests passed: \([0-9]*\).*/\1/')
        local total=$(echo "$stats" | sed 's/.*Tests passed: [0-9]*\/\([0-9]*\).*/\1/')
        
        if [[ "$passed" =~ ^[0-9]+$ && "$total" =~ ^[0-9]+$ ]]; then
            TOTAL_TESTS=$((TOTAL_TESTS + total))
            TOTAL_PASSED=$((TOTAL_PASSED + passed))
            return 0
        fi
    fi
    
    # Fallback: assume 1 test, status based on exit code
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    if [[ "${TEST_RESULTS[$test_name]}" == "PASSED" ]]; then
        TOTAL_PASSED=$((TOTAL_PASSED + 1))
    fi
}

# Generate comprehensive test report
generate_test_report() {
    local end_time=$(date +%s)
    local total_duration=$((end_time - START_TIME))
    
    echo
    log_header "═══════════════════════════════════════════════════════════"
    log_header "Harbor Test Suite Results"
    log_header "═══════════════════════════════════════════════════════════"
    echo
    
    # Test results summary
    echo -e "${BOLD}Test Results Summary:${NC}"
    echo "────────────────────────────────────────────────────────────"
    
    local suite_count=0
    local passed_suites=0
    
    # Parse results from simple string format
    IFS=';' read -ra RESULTS_ARRAY <<< "$TEST_RESULTS"
    IFS=';' read -ra TIMES_ARRAY <<< "$TEST_TIMES"
    
    for result in "${RESULTS_ARRAY[@]}"; do
        if [[ -n "$result" ]]; then
            local test_name="${result%:*}"
            local status="${result#*:}"
            
            # Find duration for this test
            local duration="0"
            for time_entry in "${TIMES_ARRAY[@]}"; do
                if [[ "$time_entry" == "$test_name:"* ]]; then
                    duration="${time_entry#*:}"
                    break
                fi
            done
            
            if [[ "$status" == "PASSED" ]]; then
                echo -e "  ✅ ${GREEN}${test_name}${NC} (${duration}s)"
                ((passed_suites++))
            else
                echo -e "  ❌ ${RED}${test_name}${NC} (${duration}s)"
            fi
            ((suite_count++))
        fi
    done
    
    echo
    
    # Overall statistics
    echo -e "${BOLD}Overall Statistics:${NC}"
    echo "────────────────────────────────────────────────────────────"
    echo "  Test Suites: $passed_suites/$suite_count passed"
    
    if [[ $TOTAL_TESTS -gt 0 ]]; then
        local success_rate=$((TOTAL_PASSED * 100 / TOTAL_TESTS))
        echo "  Individual Tests: $TOTAL_PASSED/$TOTAL_TESTS passed ($success_rate%)"
    fi
    
    echo "  Total Time: ${total_duration}s"
    echo "  Timestamp: $(date)"
    echo
    
    # Final result
    if [[ "$OVERALL_SUCCESS" == "true" ]]; then
        log_success "🎉 ALL TESTS PASSED!"
        echo "✅ Harbor test suite completed successfully"
        echo
        return 0
    else
        log_error "❌ SOME TESTS FAILED!"
        echo "⚠️  Review failed tests above and check Harbor functionality"
        echo
        
        # Provide guidance based on what failed
        if [[ "$TEST_RESULTS" == *"Core Infrastructure Tests:FAILED"* ]]; then
            echo "💡 Core infrastructure failures suggest basic Harbor setup issues"
        fi
        
        if [[ "$TEST_RESULTS" == *"Native Service Tests:FAILED"* ]]; then
            echo "💡 Native service failures suggest dependency resolution issues"
        fi
        
        if [[ "$TEST_RESULTS" == *"Routine Tests:FAILED"* ]]; then
            echo "💡 Routine test failures suggest Deno or module issues"
        fi
        
        if [[ "$TEST_RESULTS" == *"Integration Tests:FAILED"* ]]; then
            echo "💡 Integration failures suggest service startup or communication issues"
        fi
        
        echo
        return 1
    fi
}

# Main execution
main() {
    parse_args "$@"
    
    log_header "Harbor Unified Test Runner"
    log_info "Starting Harbor test suite..."
    
    # Show what will be run
    local test_plan=()
    [[ "$RUN_CORE" == "true" ]] && test_plan+=("Core Infrastructure")
    [[ "$RUN_NATIVE" == "true" ]] && test_plan+=("Native Services")
    [[ "$RUN_ROUTINES" == "true" ]] && test_plan+=("Routines")
    [[ "$RUN_INTEGRATION" == "true" ]] && test_plan+=("Integration")
    
    log_info "Test plan: ${test_plan[*]}"
    echo
    
    # Check prerequisites
    check_prerequisites
    echo
    
    # Run test suites in order
    run_core_tests
    run_native_tests
    run_routine_tests
    run_integration_tests
    
    # Generate final report
    generate_test_report
}

# Safety check
if [[ ! -f "$HARBOR_ROOT/harbor.sh" ]]; then
    log_error "Not in Harbor root directory (harbor.sh not found)"
    log_error "Please run from Harbor root: ./tests/run_tests.sh"
    exit 2
fi

# Execute main function
main "$@"