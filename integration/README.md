# Harbor Integration Tests

End-to-end smoke tests for Harbor service orchestration.

## Running Locally

Requires [Multipass](https://multipass.run) installed on the host.

```bash
harbor dev integration
```

This provisions a fresh Ubuntu VM, runs the test suite, collects artifacts, and tears down the VM automatically.

## Flags

| Flag | Description |
|------|-------------|
| `--keep-vm` | Preserve the Multipass VM after run (for debugging) |
| `--artifacts-dir <path>` | Override artifacts output directory |
| `--verbose` | Enable verbose output |

## Structure

```
integration/
  cloud-init/       Cloud-init VM configuration
  fixtures/         Deterministic test services
  guest/            Guest-side runner scripts
  http/             httpYac test suites
  lib/              Bash helper libraries
  artifacts/        Test run outputs (git-ignored)
```

## First Suite

The initial suite validates:
1. Harbor bootstrap on a clean Linux machine
2. Harbor lifecycle commands (up/ps/down)
3. HTTP contract against a deterministic mock-openai fixture

## GitHub Actions

CI runs the same guest-side logic directly on `ubuntu-latest` without a nested VM:

```bash
harbor dev integration --no-provision
```
