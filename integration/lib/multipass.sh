#!/usr/bin/env bash
# Harbor integration test Multipass helpers
# Source this file: source "$(dirname "${BASH_SOURCE[0]}")/multipass.sh"
#
# Note: These functions are provided as reference/documentation.
# The authoritative multipass orchestration lives in .scripts/integration.ts,
# which calls multipass via subprocess. These helpers can be used directly in
# bash-only contexts or for manual debugging.

# Usage: multipass_launch <vm_name> [cloud_init_path]
multipass_launch() {
  local name="$1"
  local cloud_init="${2:-./integration/cloud-init/multipass.yaml}"
  multipass launch \
    --name "$name" \
    --cpus 2 \
    --memory 4G \
    --disk 20G \
    --cloud-init "$cloud_init"
}

# Usage: multipass_mount_repo <vm_name> <host_path>
multipass_mount_repo() {
  local name="$1"
  local host_path="$2"
  multipass mount "$host_path" "$name:/workspace/harbor"
}

# Usage: multipass_teardown <vm_name>
# Stops, deletes, and purges in one step
multipass_teardown() {
  local name="$1"
  multipass stop "$name" || true
  multipass delete "$name" || true
  multipass purge || true
}

# Usage: multipass_exec <vm_name> <cmd...>
multipass_exec() {
  local name="$1"
  shift
  multipass exec "$name" -- "$@"
}
