# Fix Tests: Disk Exhaustion Incident Analysis

This spec describes the failure mode observed on 2026-06-15 during a Harbor test run, and the remediation applied in `tests/stage-repo.ts` + `tests/run.ts`.

## Incident Summary

Running the Boost agentic smoke suite made the Fedora workstation effectively unusable by exhausting the root filesystem.

The active command was:

```bash
harbor dev test --suite 06-boost-agentic-smoke
```

The test runner launched the distro matrix at approximately `12:01:52` local time. By approximately `12:23`, `/` was full and desktop/session applications began crashing or failing writes.

## Observed System State

At the point of investigation:

- `/dev/nvme0n1p3` was mounted as `/` and `/home`.
- `/` was at `100%` usage.
- The load average was around `28-35`.
- Several `tar` processes were stuck in uninterruptible I/O state (`D`).
- The stuck commands were staging `/opt/harbor-test/work` inside Harbor test containers.
- Six Harbor test containers were active:
  - `harbor-test-20260615-100153-ubuntu-2404`
  - `harbor-test-20260615-100153-ubuntu-2204`
  - `harbor-test-20260615-100153-debian-12`
  - `harbor-test-20260615-100153-fedora-43`
  - `harbor-test-20260615-100153-rocky-9`
  - `harbor-test-20260615-100153-archlinux`

After killing the test process and removing those containers, free space recovered from effectively zero to hundreds of gigabytes, confirming that the active test containers and their writable layers were the immediate disk consumer.

## Failing Operation

The active failing operation was the per-row staging copy in `tests/run.ts`:

```bash
tar -C /opt/harbor-test/repo -cf - \
  --exclude='./.env' \
  --exclude='./.git' \
  --exclude='./.history' \
  --exclude='./app' \
  --exclude='./docs' \
  --exclude='./node_modules' \
  --exclude='./services/webui' \
  --exclude='./tests/artifacts' \
  . | tar -C /opt/harbor-test/work -xf -
```

This runs once per active distro row. With the default parallelism, multiple rows performed this copy at the same time.

## Current Test Runner Behavior

The test runner bind-mounts the host repository at:

```text
/opt/harbor-test/repo
```

Then it creates a per-row writable Harbor home at:

```text
/opt/harbor-test/work
```

The implementation uses `tar | tar` to copy a selected subset of the bind-mounted repo into that writable location.

The code comments describe this area as a per-row writable Harbor home and mention overlay semantics, but the implementation observed during the incident is a real copy into the container writable layer.

## Repository Size Profile

The Harbor checkout is large enough that multiplying it by distro rows is dangerous.

A post-incident size sample showed the checkout at roughly `70G`, with large top-level contributors including:

- `services/` around `31G`
- `lemonade/` around `25G`
- `app/` around `13G`
- `.git/` around `1.8G`

The staging command excludes some large paths, including `app/`, `.git/`, `node_modules/`, and `services/webui/`, but it still copies enough repository content to become a large per-row disk allocation.

## Amplification Factor

The failure is not a single large copy. It is a multiplicative test-matrix behavior:

- one staged writable copy per distro row;
- rows run concurrently by default;
- each row has its own container writable layer;
- the Boost agentic suite also operates inside nested Docker within each row;
- Docker/containerd metadata and logs are written to the same full root filesystem.

The result is that a command intended to run one logical suite can create several large, simultaneous filesystem write workloads.

## User-Visible Failure Mode

Once the root filesystem reached `100%`, unrelated desktop and system components failed because they could no longer write state, logs, SQLite journals, caches, or coredumps.

Observed errors included:

```text
OSError: [Errno 28] No space left on device
```

and Docker/containerd errors such as:

```text
error writing log entry: no space left on device
failed to commit transaction: write ... metadata.db: no space left on device
```

Applications and services observed crashing or failing included:

- Warp terminal (`SIGBUS`)
- Zed editor (`SIGBUS`)
- `gvfsd-metadata` (`SIGBUS`, repeated)
- `packagekitd` (`SIGABRT` after SQLite disk I/O errors)
- `systemd-journald` / rsyslog write failures
- RustDesk log write failures
- Hermes write failures
- Docker and containerd metadata/log write failures

The apparent application crashes were secondary effects of filesystem exhaustion, not independent root causes.

## Root Cause

The immediate root cause was Harbor's container test runner staging large per-row writable copies of the repository into Docker container layers while running several distro rows concurrently.

The specific trigger was the Boost agentic smoke suite run across the default distro matrix:

```bash
harbor dev test --suite 06-boost-agentic-smoke
```

The root filesystem filled because the test runner multiplied a large repository staging operation across multiple active containers, while additional nested Docker activity in those containers wrote to the same host disk.

## Contributing Factors

- The checkout contains very large top-level trees that are not all needed by every test suite.
- The staging copy is real data duplication, not a lightweight view.
- Default row parallelism allows several large staging operations to overlap.
- Container writable layers, nested Docker storage, logs, and metadata all share the host root filesystem.
- The runner has a per-row timeout, but the disk exhaustion happened before timeout handling could make the system safe.
- The system had finite free space despite a large disk; the test runner did not treat available disk as a limiting resource.
- The failure cascaded into desktop apps because `/home`, `/var/lib/docker`, `/var/log`, and application state all live on the same root filesystem.

## Non-Root Causes

The evidence does not point to RAM exhaustion:

- memory remained mostly available;
- swap was essentially unused;
- the dominant failures were `ENOSPC` and write failures.

The evidence does not point to a GPU or display-server crash as the primary cause:

- application crashes coincided with `No space left on device` errors;
- affected processes included non-graphical services and databases;
- removing the Harbor test containers immediately recovered disk space.

The evidence does not point to a single misbehaving desktop application:

- failures occurred across unrelated processes;
- Docker/containerd and journald reported the same storage failure at the same time.

## Problem Statement

`harbor dev test --suite 06-boost-agentic-smoke` can consume enough host disk through concurrent per-row repository staging and nested container activity to fill the root filesystem and destabilize the entire workstation.

This made the test runner unsafe to execute on a developer machine with the current checkout size and default matrix behavior.

## Remediation (implemented)

1. **No host repo bind-mount.** Before any row starts, `run.ts` calls `materializeTrackedRepo()` once per run. Only paths from `git ls-files` are copied into `tests/artifacts/<run-id>/staged-repo/`. Untracked and gitignored local trees never enter the matrix.

2. **Read-only artifact mount.** Rows mount the staged directory at `/opt/harbor-test/repo:ro`, not `REPO_ROOT`.

3. **No per-row bulk copy.** `prepareHarborWork()` creates an empty `/opt/harbor-test/work`. The install suite copies from the bounded staged tree when needed (~tens of MiB, not tens of GiB).

4. **Disk preflight.** `assertDiskHeadroom()` refuses to start when free space is insufficient for concurrent rows.

5. **Heavy suite defaults.** `boost-agentic-smoke` defaults to `--distros fedora-43 --jobs 1` unless overridden.

6. **Regression tests.** `tests/run-stage.test.ts` asserts staging bounds and that `run.ts` never bind-mounts `REPO_ROOT` or runs in-container `tar` copies.
