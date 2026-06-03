---
name: agent-integration-testing
description: Use when the user requests integration testing, feature validation, or test plan execution
---

# Agent Integration Testing

## Overview
This skill guides the creation and autonomous execution of verifiable integration test specifications. It ensures that tests are actionable by agents, properly documented, and systematically executed by subagents to validate features or fix failures.

## Core Process

1. **Investigate Codebase Area**
   - By default, investigate the entire codebase to understand the context.
   - If the user specifies a feature area, use `glob` and `grep` to narrow the investigation.

2. **Write Test Specification**
   - Create a test spec file at `./tests/<name>.md`.
   - Use `<name> = "integration"` unless the user specifies a particular feature area.
   - The document MUST include a **Prerequisites** section at the top detailing any setup needed before tests become runnable (e.g., environment variables, database seeding, background services).

3. **Define Verifiable Tests**
   - Each test must be written in plain English.
   - Include clear **steps to reproduce**.
   - Include a set of **expectations**.
   - **CRITICAL:** Every expectation must be strictly verifiable by an agent using available tools (e.g., shell commands, HTTP requests, reading file outputs). If a test cannot be verified by an agent, it is invalid and must be rewritten or removed.

4. **Execute Tests via Subagents**
   - Spawn subagents (using the `Task` tool or `@mention` subagent system) to run each individual test.
   - The subagent must follow the prerequisites, execute the steps, and validate the outcomes against the expectations.
   - Collect the results (Pass/Fail and logs) from the subagents.

5. **Fix Failures (Optional)**
   - If the user explicitly specifies that failures should be fixed, spawn another subagent (e.g., the `SWE` or `BUILDER` agent) to investigate and fix any noted failures.

## Quick Reference

| Action | Pattern / Command |
|--------|-------------------|
| Test File Location | `./tests/<name>.md` (default: `integration.md`) |
| Prerequisites | Must be documented at the top of the test file |
| Test Format | Plain English, Repro Steps, Verifiable Expectations |
| Execution | Spawn one subagent per test or test suite |
| Fixing | Spawn SWE/BUILDER subagent if requested by user |

## Red Flags - STOP and Start Over

- **Unverifiable Tests:** "Verify the UI looks nice" or "Check if the animation is smooth." (Agents cannot verify visual aesthetics without specific tools). **Fix:** Rewrite to check DOM elements, network responses, or file states.
- **Missing Prerequisites:** Subagents failing because the server wasn't started. **Fix:** Ensure the prerequisite section explicitly defines the commands to start dependencies.
- **Executing Tests Manually:** Running tests in the main conversation thread instead of spawning subagents. **Fix:** Dispatch parallel subagents for isolated execution.

## Example Test Specification (`./tests/auth-integration.md`)

```markdown
# Auth Integration Tests

## Prerequisites
- Start the test database: `docker compose up -d db`
- Run migrations: `npm run migrate`
- Start the server in background: `npm run start:test &`

## Test 1: User Registration
**Steps:**
1. Send a POST request to `/api/register` with payload `{"email": "test@example.com", "password": "pass"}`.

**Expectations:**
1. The HTTP response status must be `201 Created`.
2. A subsequent query to the database using `sqlite3 test.db "SELECT email FROM users WHERE email='test@example.com';"` must return the email.
```
