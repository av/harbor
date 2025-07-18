# Harbor Test Suite

This directory contains Harbor's consolidated test suite, organized for clarity, maintainability, and comprehensive coverage of Harbor's functionality.

## Test Structure

### Directory Organization

```
tests/
├── README.md                           # This file - test structure and usage
├── run_tests.sh                        # Unified test runner for all test types
├── test_harbor_core.sh                 # Core Harbor infrastructure tests
├── test_native_services.sh             # Native service functionality tests
└── test_native_integration.sh          # End-to-end integration tests

routines/tests/
├── test_startup_computation.js         # Deno tests for startup wave computation
└── test_dependency_extraction.js       # Deno tests for dependency extraction
```

### Test Categories

#### 1. Core Infrastructure Tests (`test_harbor_core.sh`)
**Purpose**: Validates basic Harbor functionality without starting services
**Coverage**:
- Harbor executable and CLI functionality
- Routines infrastructure (loadNativeConfig.js, docker.js, etc.)
- Compose file structure validation
- System dependencies (Docker, jq, nc)
- Environment and configuration system
- Documentation structure

**Safety**: No services started, no network operations, read-only

#### 2. Native Service Tests (`test_native_services.sh`)
**Purpose**: Tests Harbor's native service dependency resolution and orchestration
**Coverage**:
- Native service infrastructure
- Configuration parsing via loadNativeConfig.js
- Race condition detection and fixes
- Dependency wave computation
- Interleaved native/container patterns
- Circular dependency detection
- Fallback behavior validation

**Safety**: Logic testing only, synthetic configs, no real service startup

#### 3. Integration Tests (`test_native_integration.sh`)
**Purpose**: End-to-end testing with actual Harbor services
**Coverage**:
- Native service launch (speaches as primary example)
- Container mode validation
- Mixed native/container orchestration
- Service dependency resolution
- Cross-service communication
- Service restart and recovery
- API endpoint validation

**Safety**: Proper cleanup, timeout protection, services stopped after tests

#### 4. Deno Routine Tests (`routines/tests/`)
**Purpose**: Unit tests for Harbor's TypeScript/JavaScript routines
**Coverage**:
- Startup computation algorithms
- Dependency extraction from compose files
- Topological sorting and wave computation
- Circular dependency detection
- Harbor routine module functionality

**Safety**: Pure function testing, no system interactions

## Quick Start

### Run All Tests
```bash
# From Harbor root directory
./tests/run_tests.sh
```

### Run Specific Test Categories
```bash
# Core infrastructure only
./tests/test_harbor_core.sh

# Native service functionality
./tests/test_native_services.sh

# Integration tests (starts real services)
./tests/test_native_integration.sh

# Deno routine tests
cd routines
deno test --allow-read --allow-env --unstable-sloppy-imports --no-check tests/
```

### Run Specific Test Scenarios
```bash
# Test specific functionality
./tests/test_native_services.sh --verify-bug
./tests/test_native_services.sh --verify-fix
./tests/test_native_services.sh --test-interleaved

# Test specific integrations
./tests/test_native_integration.sh --test-speaches
./tests/test_native_integration.sh --test-communication
./tests/test_native_integration.sh --test-dependencies
```

## Test Development Guidelines

### Adding New Tests

#### For Core Infrastructure Tests
- Add to `test_harbor_core.sh`
- Keep tests safe (no service startup, no system modifications)
- Focus on Harbor's basic functionality
- Add meaningful error messages and actions

#### For Native Service Tests
- Add to `test_native_services.sh`
- Test logic only, use synthetic configurations
- Include actionable failure guidance
- Test both success and failure scenarios

#### For Integration Tests
- Add to `test_native_integration.sh`
- Include proper cleanup in test functions
- Use timeout protection for all operations
- Test real service interactions

#### For Routine Tests
- Add to `routines/tests/`
- Write proper Deno test functions
- Test edge cases and error conditions
- Keep tests isolated and independent

### Test Function Structure

```bash
# Shell test function template
test_function_name() {
    log_info "Testing specific functionality..."
    
    # Setup
    setup_test_environment
    
    # Test logic
    if test_condition; then
        test_result "Test name" true "Success message"
    else
        test_result "Test name" false "Failure message" "Action to fix"
    fi
    
    # Cleanup
    cleanup_test_environment
}
```

```javascript
// Deno test function template
Deno.test("descriptive test name", async () => {
    // Setup
    const testData = setupTestData();
    
    // Test logic
    const result = await functionUnderTest(testData);
    
    // Assertions
    assertEquals(result.success, true);
    assertEquals(result.data.length, expectedLength);
});
```

### Test Result Tracking

All tests use consistent result tracking:
- `test_result(name, passed, message, action)` for shell tests
- Standard Deno assertions for routine tests
- Comprehensive summary reporting
- Actionable failure guidance

## Running Tests in Development

### Prerequisites
- Harbor must be properly installed
- Docker must be running (for integration tests)
- Deno must be installed (for routine tests)
- Required system tools: `jq`, `nc`, `curl`

### Development Workflow

```bash
# 1. Run core tests first (fastest, safest)
./tests/test_harbor_core.sh

# 2. Run native service tests (logic only)
./tests/test_native_services.sh

# 3. Run routine tests (unit tests)
cd routines && deno test --allow-read --allow-env --unstable-sloppy-imports --no-check tests/

# 4. Run integration tests (slowest, starts services)
./tests/test_native_integration.sh --test-speaches  # Test specific service first
./tests/test_native_integration.sh                  # Full integration suite
```

### Debugging Test Failures

#### Core Infrastructure Failures
- Check Harbor installation and file permissions
- Verify system dependencies are installed
- Ensure you're running from Harbor root directory

#### Native Service Test Failures
- Check Deno installation and permissions
- Verify Harbor routines are present and syntactically correct
- Review test synthetic configurations

#### Integration Test Failures
- Check Docker is running and accessible
- Verify service configurations are correct
- Review service logs for startup issues
- Check network connectivity and port availability

#### Routine Test Failures
- Check Deno import paths and module availability
- Verify test data and mock configurations
- Review function signatures and expected behavior

## Test Maintenance

### Regular Tasks
- Run full test suite before commits
- Update tests when adding new Harbor functionality
- Review and update synthetic test configurations
- Validate test coverage for new features

### Periodic Tasks
- Review test execution time and optimize slow tests
- Update test documentation for new features
- Refactor redundant or overlapping tests
- Update integration test scenarios for new services

### Quality Assurance
- All tests must pass before merging changes
- New functionality must include appropriate tests
- Test failures must include actionable guidance
- Integration tests must properly clean up resources

## Troubleshooting

### Common Issues

#### "Harbor executable not found"
- Ensure you're running from Harbor root directory
- Check `harbor.sh` exists and is executable
- Verify file permissions

#### "Deno not available"
- Install Deno runtime: `curl -fsSL https://deno.land/install.sh | sh`
- Add Deno to PATH
- Verify installation: `deno --version`

#### "Docker not available"
- Start Docker daemon
- Check Docker access: `docker ps`
- Verify Docker Compose is available

#### "Service not ready" in integration tests
- Check service logs: `./harbor.sh logs <service>`
- Verify service configuration
- Check port availability
- Increase timeout values if needed

#### "Import errors" in Deno tests
- Use correct flags: `--unstable-sloppy-imports --no-check`
- Verify module paths are correct
- Check routine files exist and are syntactically correct

### Getting Help

1. **Check test output**: Most failures include specific error messages and suggested actions
2. **Review logs**: Integration tests log service startup and behavior
3. **Verify environment**: Ensure all prerequisites are met
4. **Run individual tests**: Isolate failures by running specific test categories
5. **Check Harbor documentation**: Review relevant Harbor documentation for context

## Contributing

### Before Submitting Changes
1. Run the full test suite: `./tests/run_tests.sh`
2. Add appropriate tests for new functionality
3. Update documentation if test structure changes
4. Ensure all tests pass and include meaningful output

### Test Coverage Goals
- **Core Infrastructure**: 100% of basic Harbor functionality
- **Native Services**: All dependency resolution scenarios
- **Integration**: Key service combinations and communication patterns
- **Routines**: All public functions and edge cases

### Quality Standards
- Tests must be deterministic and repeatable
- Integration tests must clean up properly
- Error messages must be actionable
- Test execution time should be reasonable
- Documentation must be kept up-to-date

---

**Last Updated**: January 2025  
**Test Suite Version**: 1.0  
**Harbor Version**: native-services branch  
**Total Test Files**: 7 (consolidated from 10 original files)