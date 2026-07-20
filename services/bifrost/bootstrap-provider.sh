#!/bin/sh
set -eu

BIFROST_URL="${BIFROST_URL:-http://bifrost:8080}"
BIFROST_PROVIDER="${BIFROST_PROVIDER:?BIFROST_PROVIDER is required}"
BIFROST_PROVIDER_KIND="${BIFROST_PROVIDER_KIND:-custom-openai}"
BIFROST_PROVIDER_BASE_URL="${BIFROST_PROVIDER_BASE_URL:?BIFROST_PROVIDER_BASE_URL is required}"
BIFROST_KEY_ID="${BIFROST_KEY_ID:-harbor-${BIFROST_PROVIDER}}"
BIFROST_KEY_NAME="${BIFROST_KEY_NAME:-Harbor ${BIFROST_PROVIDER}}"
BIFROST_PROVIDER_KEY="${BIFROST_PROVIDER_KEY:-}"
BIFROST_MODELS="${BIFROST_MODELS:-*}"

wait_for_bifrost() {
  i=0
  while [ "$i" -lt 120 ]; do
    if curl -fsS "$BIFROST_URL/health" >/dev/null 2>&1; then
      return 0
    fi
    i=$((i + 1))
    sleep 1
  done

  echo "Timed out waiting for Bifrost at $BIFROST_URL" >&2
  return 1
}

request() {
  method="$1"
  url="$2"
  data="${3:-}"
  body_file="$(mktemp -t harbor.XXXXXX)"

  if [ -n "$data" ]; then
    status="$(curl -sS -o "$body_file" -w '%{http_code}' -X "$method" "$url" \
      -H 'Content-Type: application/json' \
      --data "$data" || printf '000')"
  else
    status="$(curl -sS -o "$body_file" -w '%{http_code}' -X "$method" "$url" || printf '000')"
  fi

  cat "$body_file" >&2
  rm -f "$body_file"
  printf '%s' "$status"
}

json_array_from_lines() {
  first=1
  printf '['
  while IFS= read -r item; do
    [ -n "$item" ] || continue
    escaped="$(printf '%s' "$item" | sed 's/\\/\\\\/g; s/"/\\"/g')"
    if [ "$first" -eq 1 ]; then
      first=0
    else
      printf ','
    fi
    printf '"%s"' "$escaped"
  done
  printf ']'
}

models_json() {
  if [ "$BIFROST_PROVIDER_KIND" != "ollama" ] && [ "$BIFROST_MODELS" = "*" ]; then
    ids="$(curl -fsS "$BIFROST_PROVIDER_BASE_URL/v1/models" 2>/dev/null \
      | grep -o '"id"[[:space:]]*:[[:space:]]*"[^"]*"' \
      | sed 's/^[^:]*:[[:space:]]*"//; s/"$//' \
      | sort -u || true)"
    if [ -n "$ids" ]; then
      printf '%s\n' "$ids" | json_array_from_lines
      return 0
    fi

    echo "Could not discover models from $BIFROST_PROVIDER_BASE_URL/v1/models" >&2
    return 1
  fi

  printf '%s' "$BIFROST_MODELS" | tr ',' '\n' | json_array_from_lines
}

key_body() {
  models="$(models_json)"
  if [ "$BIFROST_PROVIDER_KIND" = "ollama" ]; then
    cat <<JSON
{"id":"$BIFROST_KEY_ID","name":"$BIFROST_KEY_NAME","value":"","models":$models,"weight":1.0,"enabled":true,"ollama_key_config":{"url":"$BIFROST_PROVIDER_BASE_URL"}}
JSON
  else
    cat <<JSON
{"id":"$BIFROST_KEY_ID","name":"$BIFROST_KEY_NAME","value":"$BIFROST_PROVIDER_KEY","models":$models,"weight":1.0,"enabled":true}
JSON
  fi
}

provider_create_body() {
  key_json="$(key_body)"
  if [ "$BIFROST_PROVIDER_KIND" = "ollama" ]; then
    cat <<JSON
{"provider":"$BIFROST_PROVIDER","keys":[$key_json],"network_config":{"base_url":"$BIFROST_PROVIDER_BASE_URL","default_request_timeout_in_seconds":300},"concurrency_and_buffer_size":{"concurrency":1000,"buffer_size":5000}}
JSON
  else
    cat <<JSON
{"provider":"$BIFROST_PROVIDER","keys":[$key_json],"network_config":{"base_url":"$BIFROST_PROVIDER_BASE_URL","default_request_timeout_in_seconds":300},"concurrency_and_buffer_size":{"concurrency":1000,"buffer_size":5000},"custom_provider_config":{"base_provider_type":"openai","allowed_requests":{"list_models":true,"text_completion":true,"text_completion_stream":true,"chat_completion":true,"chat_completion_stream":true,"responses":false,"responses_stream":false,"count_tokens":false,"embedding":true,"speech":false,"speech_stream":false,"transcription":false,"transcription_stream":false,"image_generation":false,"image_generation_stream":false,"batch_create":false,"batch_list":false,"batch_retrieve":false,"batch_cancel":false,"batch_results":false,"file_upload":false,"file_list":false,"file_retrieve":false,"file_delete":false,"file_content":false}}}
JSON
  fi
}

provider_update_body() {
  key_json="$(key_body)"
  if [ "$BIFROST_PROVIDER_KIND" = "ollama" ]; then
    cat <<JSON
{"keys":[$key_json],"network_config":{"base_url":"$BIFROST_PROVIDER_BASE_URL","default_request_timeout_in_seconds":300},"concurrency_and_buffer_size":{"concurrency":1000,"buffer_size":5000}}
JSON
  else
    cat <<JSON
{"keys":[$key_json],"network_config":{"base_url":"$BIFROST_PROVIDER_BASE_URL","default_request_timeout_in_seconds":300},"concurrency_and_buffer_size":{"concurrency":1000,"buffer_size":5000},"custom_provider_config":{"base_provider_type":"openai","allowed_requests":{"list_models":true,"text_completion":true,"text_completion_stream":true,"chat_completion":true,"chat_completion_stream":true,"responses":false,"responses_stream":false,"count_tokens":false,"embedding":true,"speech":false,"speech_stream":false,"transcription":false,"transcription_stream":false,"image_generation":false,"image_generation_stream":false,"batch_create":false,"batch_list":false,"batch_retrieve":false,"batch_cancel":false,"batch_results":false,"file_upload":false,"file_list":false,"file_retrieve":false,"file_delete":false,"file_content":false}}}
JSON
  fi
}

ensure_key_endpoint() {
  # GET /api/providers/<name> redacts keys — the keys list has its own endpoint.
  provider_json="$(curl -fsS "$BIFROST_URL/api/providers/$BIFROST_PROVIDER/keys" || true)"
  if ! printf '%s' "$provider_json" | grep -q '"keys":\['; then
    provider_json="$(curl -fsS "$BIFROST_URL/api/providers/$BIFROST_PROVIDER" || true)"
  fi
  if printf '%s' "$provider_json" | grep -q '"keys":\[' && \
    { printf '%s' "$provider_json" | grep -q "\"$BIFROST_KEY_ID\"" || printf '%s' "$provider_json" | grep -q "\"$BIFROST_KEY_NAME\""; }; then
    echo "Provider key $BIFROST_KEY_ID present"
    return 0
  fi

  key_json="$(key_body)"
  key_status="$(request POST "$BIFROST_URL/api/providers/$BIFROST_PROVIDER/keys" "$key_json")"
  case "$key_status" in
    200|201)
      echo "Provider key $BIFROST_KEY_ID created"
      ;;
    405)
      echo "Provider key endpoint is unavailable and embedded key was not visible for $BIFROST_PROVIDER" >&2
      exit 1
      ;;
    409)
      update_key_status="$(request PUT "$BIFROST_URL/api/providers/$BIFROST_PROVIDER/keys/$BIFROST_KEY_ID" "$key_json")"
      case "$update_key_status" in
        200|201) echo "Provider key $BIFROST_KEY_ID updated" ;;
        *) echo "Failed to update key $BIFROST_KEY_ID: HTTP $update_key_status" >&2; exit 1 ;;
      esac
      ;;
    *)
      echo "Failed to create key $BIFROST_KEY_ID: HTTP $key_status" >&2
      exit 1
      ;;
  esac
}

wait_for_bifrost

create_body="$(provider_create_body)"
provider_status="$(request POST "$BIFROST_URL/api/providers" "$create_body")"
case "$provider_status" in
  200|201)
    echo "Provider $BIFROST_PROVIDER created"
    ;;
  409)
    update_body="$(provider_update_body)"
    update_status="$(request PUT "$BIFROST_URL/api/providers/$BIFROST_PROVIDER" "$update_body")"
    case "$update_status" in
      200|201) echo "Provider $BIFROST_PROVIDER updated" ;;
      *) echo "Failed to update provider $BIFROST_PROVIDER: HTTP $update_status" >&2; exit 1 ;;
    esac
    ;;
  *)
    echo "Failed to create provider $BIFROST_PROVIDER: HTTP $provider_status" >&2
    exit 1
    ;;
esac

ensure_key_endpoint
