#!/usr/bin/env bash
# Harbor integration test readiness helpers
# Source this file: source "$(dirname "${BASH_SOURCE[0]}")/readiness.sh"

log_info()  { echo "[INFO]  $(date +%H:%M:%S) $*"; }
log_warn()  { echo "[WARN]  $(date +%H:%M:%S) $*" >&2; }
log_error() { echo "[ERROR] $(date +%H:%M:%S) $*" >&2; }

# Usage: wait_for_url <url> [max_attempts] [sleep_seconds]
# Polls the URL with curl until HTTP 200 or timeout
# Default: 30 attempts, 2s sleep
wait_for_url() {
  local url="$1"
  local max_attempts="${2:-30}"
  local sleep_secs="${3:-2}"

  log_info "Waiting for $url (max ${max_attempts} attempts, ${sleep_secs}s interval)"

  local attempt=1
  while [[ $attempt -le $max_attempts ]]; do
    local http_code
    http_code=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 "$url" 2>/dev/null || true)

    if [[ "$http_code" == "200" ]]; then
      log_info "URL $url responded 200 (attempt $attempt)"
      return 0
    fi

    log_info "Attempt $attempt/$max_attempts — got '${http_code:-no response}', retrying in ${sleep_secs}s..."
    sleep "$sleep_secs"
    (( attempt++ ))
  done

  log_error "Timed out waiting for $url after $max_attempts attempts"
  return 1
}

# Usage: wait_for_container <container_name_or_id> [max_attempts]
# Waits until docker inspect shows container running
wait_for_container() {
  local container="$1"
  local max_attempts="${2:-30}"

  log_info "Waiting for container '$container' to be running (max $max_attempts attempts)"

  local attempt=1
  while [[ $attempt -le $max_attempts ]]; do
    local status
    status=$(docker inspect --format '{{.State.Status}}' "$container" 2>/dev/null || true)

    if [[ "$status" == "running" ]]; then
      log_info "Container '$container' is running (attempt $attempt)"
      return 0
    fi

    log_info "Attempt $attempt/$max_attempts — status='${status:-unknown}', retrying in 2s..."
    sleep 2
    (( attempt++ ))
  done

  log_error "Timed out waiting for container '$container' after $max_attempts attempts"
  return 1
}

# Usage: wait_for_http <url> [timeout_seconds] [interval_seconds]
# Polls the URL with curl until HTTP 200 or timeout (in wall-clock seconds)
# Default: 60s timeout, 3s interval
wait_for_http() {
  local url="$1"
  local timeout="${2:-60}"
  local interval="${3:-3}"
  local elapsed=0

  log_info "Waiting for $url (timeout: ${timeout}s)"
  until curl -sf "$url" > /dev/null 2>&1; do
    if [[ $elapsed -ge $timeout ]]; then
      log_error "Timed out waiting for $url after ${elapsed}s"
      return 1
    fi
    sleep "$interval"
    elapsed=$(( elapsed + interval ))
  done
  log_info "  $url is ready (${elapsed}s)"
}

# Returns 0 if docker daemon is accessible, 1 otherwise
check_docker_running() {
  docker info > /dev/null 2>&1
}
