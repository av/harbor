#!/usr/bin/env bash
# Harbor Launch Walkthrough Demo
#
# Sequential two-pane tmux walkthrough for `harbor launch`.
#
# Pane layout:
#   top    narrative for the current step
#   bottom command typed and executed live
#
# Story:
#   Opening - summarize the launch route
#   1. Show Harbor status with `harbor ps`
#   2. Generate host-tool config with `harbor launch --config`
#   3. Launch a host tool directly against a local backend
#   4. Prove `harbor launch --web` by showing services before and after it runs
#
# Boost and SearXNG are not pre-started by this script. Step 4 intentionally
# lets `harbor launch --web` do that work so the automation is visible.

set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]}"
if [[ "$SCRIPT_PATH" != /* ]]; then
    SCRIPT_PATH="$PWD/$SCRIPT_PATH"
fi

SESSION="harbor-launch-walkthrough-$$"
WINDOW="walkthrough"

BACKEND="${HARBOR_DEMO_BACKEND:-llamacpp}"
MODEL="${HARBOR_DEMO_MODEL:-}"
TOOL="${HARBOR_DEMO_TOOL:-mi}"
TASK="${HARBOR_DEMO_TASK:-Explain what harbor launch does in one sentence.}"
WEB_TASK="${HARBOR_DEMO_WEB_TASK:-Use web search to find one current fact about local LLM tools, then answer in one sentence.}"
STEP_DELAY="${HARBOR_DEMO_STEP_DELAY:-4}"
HOLD_DELAY="${HARBOR_DEMO_HOLD_DELAY:-7}"
TYPE_DELAY="${HARBOR_DEMO_TYPE_DELAY:-0.025}"
COMMAND_TIMEOUT="${HARBOR_DEMO_COMMAND_TIMEOUT:-600}"

DRY_RUN=false
SKIP_PROMPT=false
ALLOW_MISSING_TOOL=false

NARRATIVE_PANE=""
ACTION_PANE=""
NARRATIVE_FILE=""
MARKER_FILE=""
STATUS_FILE=""
STATE_FILE=""
DRIVER_FILE=""

TOOL_ARGS=()
TOTAL_STEPS=4

sq() {
    printf '%q' "$1"
}

cmd_exists() {
    command -v "$1" >/dev/null 2>&1
}

log() {
    echo "-> $*"
}

warn() {
    echo "WARNING: $*" >&2
}

err() {
    echo "ERROR: $*" >&2
    exit 1
}

usage() {
    cat <<'HELP'
Usage: launch-walkthrough.sh [OPTIONS]

Options:
  --backend SERVICE       Harbor backend (default: llamacpp)
  --model ID              Model to pass explicitly (default: auto-discover)
  --tool TOOL             Host tool to demo (default: mi)
  --task PROMPT           Prompt for the direct launch step
  --web-task PROMPT       Prompt for the web-enabled launch step
  --step-delay SECS       Pause before a command is typed (default: 4)
  --hold-delay SECS       Pause after command output (default: 7)
  --type-delay SECS       Per-character typing delay (default: 0.025)
  --command-timeout SECS  Max seconds to wait for a command marker (default: 600)
  --allow-missing-tool    Show would-run commands instead of failing if TOOL is absent
  --yes                   Skip confirmation prompt
  --dry-run               Print the planned steps and exit
  -h, --help              Show this help

Environment variables:
  HARBOR_DEMO_BACKEND          Default backend
  HARBOR_DEMO_MODEL            Default model (empty = auto-discover)
  HARBOR_DEMO_TOOL             Default host tool
  HARBOR_DEMO_TASK             Default direct-launch prompt
  HARBOR_DEMO_WEB_TASK         Default web-enabled prompt
  HARBOR_DEMO_STEP_DELAY       Default pause before commands
  HARBOR_DEMO_HOLD_DELAY       Default pause after visible commands
  HARBOR_DEMO_TYPE_DELAY       Default per-character typing delay
  HARBOR_DEMO_COMMAND_TIMEOUT  Default command completion timeout

Supported walkthrough tools:
  codex, grok, hermes, mi, opencode, pi

Examples:
  ./scripts/demos/launch-walkthrough.sh
  ./scripts/demos/launch-walkthrough.sh --dry-run
  ./scripts/demos/launch-walkthrough.sh --backend ollama --model qwen3.5:4b
  ./scripts/demos/launch-walkthrough.sh --tool codex --task "What is 2+2?"
  ./scripts/demos/launch-walkthrough.sh --allow-missing-tool --tool pi
  ./scripts/demos/launch-walkthrough.sh --yes --step-delay 2 --hold-delay 5 --type-delay 0.005
HELP
}

parse_args() {
    while [ $# -gt 0 ]; do
        case "$1" in
        --backend)
            [ -n "${2:-}" ] || err "Usage: --backend <service>"
            BACKEND="$2"
            shift 2
            ;;
        --model)
            [ -n "${2:-}" ] || err "Usage: --model <model-id>"
            MODEL="$2"
            shift 2
            ;;
        --tool)
            [ -n "${2:-}" ] || err "Usage: --tool <tool>"
            TOOL="$2"
            shift 2
            ;;
        --task)
            [ -n "${2:-}" ] || err "Usage: --task <prompt>"
            TASK="$2"
            shift 2
            ;;
        --web-task)
            [ -n "${2:-}" ] || err "Usage: --web-task <prompt>"
            WEB_TASK="$2"
            shift 2
            ;;
        --step-delay)
            [ -n "${2:-}" ] || err "Usage: --step-delay <seconds>"
            STEP_DELAY="$2"
            shift 2
            ;;
        --hold-delay)
            [ -n "${2:-}" ] || err "Usage: --hold-delay <seconds>"
            HOLD_DELAY="$2"
            shift 2
            ;;
        --type-delay)
            [ -n "${2:-}" ] || err "Usage: --type-delay <seconds>"
            TYPE_DELAY="$2"
            shift 2
            ;;
        --command-timeout)
            [ -n "${2:-}" ] || err "Usage: --command-timeout <seconds>"
            COMMAND_TIMEOUT="$2"
            shift 2
            ;;
        --allow-missing-tool)
            ALLOW_MISSING_TOOL=true
            shift
            ;;
        --yes)
            SKIP_PROMPT=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            err "Unknown option: $1"
            ;;
        esac
    done
}

validate_seconds() {
    local name="$1" value="$2"
    if ! [[ "$value" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
        err "$name must be a non-negative number of seconds"
    fi
}

validate_positive_integer() {
    local name="$1" value="$2"
    if ! [[ "$value" =~ ^[1-9][0-9]*$ ]]; then
        err "$name must be a positive integer"
    fi
}

demo_tools() {
    echo "codex grok hermes mi opencode pi"
}

validate_tool() {
    case "$TOOL" in
    codex|grok|hermes|mi|opencode|pi)
        return 0
        ;;
    claude)
        err "Claude Code does not support --web in harbor launch. Choose one of: $(demo_tools)"
        ;;
    *)
        err "Unsupported demo tool '$TOOL'. Choose one of: $(demo_tools)"
        ;;
    esac
}

validate_config() {
    validate_tool
    validate_seconds "--step-delay" "$STEP_DELAY"
    validate_seconds "--hold-delay" "$HOLD_DELAY"
    validate_seconds "--type-delay" "$TYPE_DELAY"
    validate_positive_integer "--command-timeout" "$COMMAND_TIMEOUT"
}

tool_label() {
    case "$1" in
    codex)    echo "OpenAI Codex" ;;
    grok)     echo "Grok" ;;
    hermes)   echo "Hermes" ;;
    mi)       echo "mi" ;;
    opencode) echo "OpenCode" ;;
    pi)       echo "pi" ;;
    *)        echo "$1" ;;
    esac
}

find_glow() {
    if cmd_exists glow; then
        echo "glow"
    elif [ -x "${HOME}/.local/bin/glow" ]; then
        echo "${HOME}/.local/bin/glow"
    else
        echo ""
    fi
}

set_tool_args() {
    local tool="$1" prompt="$2"
    TOOL_ARGS=()
    case "$tool" in
    codex)
        TOOL_ARGS=(exec --skip-git-repo-check --sandbox read-only --color never "$prompt")
        ;;
    grok)
        TOOL_ARGS=(-p "$prompt" --no-wait-for-background)
        ;;
    hermes)
        TOOL_ARGS=(chat -Q -q "$prompt")
        ;;
    mi|pi)
        TOOL_ARGS=(-p "$prompt")
        ;;
    opencode)
        TOOL_ARGS=(run "$prompt")
        ;;
    esac
}

join_cmd() {
    local out="" arg quoted
    for arg in "$@"; do
        quoted=$(sq "$arg")
        out+="${out:+ }${quoted}"
    done
    printf '%s\n' "$out"
}

launch_cmd() {
    local mode="$1"
    shift

    local args=(harbor launch)
    if [ -n "$mode" ]; then
        args+=("$mode")
    fi
    if [ -n "$MODEL" ]; then
        args+=(--model "$MODEL")
    fi
    args+=(--backend "$BACKEND")
    args+=("$@")

    join_cmd "${args[@]}"
}

direct_launch_cmd() {
    set_tool_args "$TOOL" "$TASK"
    launch_cmd "" "$TOOL" "${TOOL_ARGS[@]}"
}

web_launch_cmd() {
    set_tool_args "$TOOL" "$WEB_TASK"
    launch_cmd "--web" "$TOOL" "${TOOL_ARGS[@]}"
}

missing_tool_cmd() {
    local would_run="$1"
    join_cmd printf '%s\n' \
        "Host tool '$TOOL' is not installed on the host." \
        "Would run: $would_run"
}

action_cmd_for() {
    local planned="$1"
    if cmd_exists "$TOOL"; then
        printf '%s\n' "$planned"
    else
        missing_tool_cmd "$planned"
    fi
}

service_is_running() {
    harbor ps 2>/dev/null | awk -v svc="$1" '
        {
            for (i = 1; i <= NF; i++) {
                if ($i == svc) found = 1
            }
        }
        END { exit found ? 0 : 1 }
    '
}

check_prereqs() {
    cmd_exists tmux || err "tmux is required. Install it first."
    cmd_exists harbor || err "harbor is not on PATH. Run: export PATH=\"$PWD:\$PATH\""

    if ! cmd_exists "$TOOL"; then
        if [ "$ALLOW_MISSING_TOOL" = true ]; then
            warn "Host tool '$TOOL' is not installed."
            warn "Direct and web steps will show the command instead of running it."
        else
            err "Host tool '$TOOL' is not installed. Install it or rerun with --allow-missing-tool."
        fi
    fi
}

normalize_term_for_tmux() {
    if [ -z "${TERM:-}" ]; then
        export TERM=xterm-256color
        return 0
    fi

    if cmd_exists infocmp && ! infocmp "$TERM" >/dev/null 2>&1; then
        warn "TERM '$TERM' is not available to tmux; using xterm-256color."
        export TERM=xterm-256color
    fi
}

ensure_backend() {
    if service_is_running "$BACKEND"; then
        log "$BACKEND is already running."
        return 0
    fi

    warn "$BACKEND is not running. Starting: harbor up $BACKEND"
    harbor up "$BACKEND"
}

print_dry_run() {
    echo
    echo "===== Dry run ====="
    echo
    echo "Backend:         $BACKEND"
    echo "Model:           ${MODEL:-auto-discover}"
    echo "Tool:            $TOOL ($(tool_label "$TOOL"))"
    echo "Direct task:     $TASK"
    echo "Web task:        $WEB_TASK"
    echo "Step delay:      ${STEP_DELAY}s"
    echo "Hold delay:      ${HOLD_DELAY}s"
    echo "Type delay:      ${TYPE_DELAY}s"
    echo "Command timeout: ${COMMAND_TIMEOUT}s"
    echo "Missing tool:    $([ "$ALLOW_MISSING_TOOL" = true ] && echo would-run || echo fail-fast)"
    echo
    echo "--- Opening: Launch route ---"
    echo "  local backend -> host tool config -> direct launch -> web-enabled routing"
    echo
    echo "--- Step 1: Status ---"
    echo "  harbor ps"
    echo
    echo "--- Step 2: Config ---"
    echo "  $(launch_cmd "" --config "$TOOL")"
    echo
    echo "--- Step 3: Direct launch ---"
    echo "  $(direct_launch_cmd)"
    echo
    echo "--- Step 4: Web tools ---"
    echo "  harbor ps                 # Before --web"
    echo "  $(web_launch_cmd)"
    echo "  harbor ps                 # After --web"
    echo
}

setup_tmux() {
    NARRATIVE_FILE=$(mktemp "/tmp/${SESSION}-narrative-XXXXXX")
    MARKER_FILE=$(mktemp "/tmp/${SESSION}-marker-XXXXXX")
    STATUS_FILE=$(mktemp "/tmp/${SESSION}-status-XXXXXX")

    tmux new-session -d -s "$SESSION" -n "$WINDOW" -x 200 -y 60
    tmux split-window -v -t "$SESSION:$WINDOW.0" -p 65 "$(action_shell_cmd)"

    NARRATIVE_PANE="$SESSION:$WINDOW.0"
    ACTION_PANE="$SESSION:$WINDOW.1"

    tmux select-pane -t "$NARRATIVE_PANE" -T "Narrative"
    tmux select-pane -t "$ACTION_PANE" -T "Action"

    tmux set-option -t "$SESSION" status on
    tmux set-option -t "$SESSION" status-interval 1
    tmux set-option -t "$SESSION" status-left " #[bg=colour26,fg=colour231,bold] Harbor Launch Walkthrough #[default] "
    tmux set-option -t "$SESSION" status-right " #[bg=colour28,fg=colour231] ${BACKEND} / $(tool_label "$TOOL") #[default] "
    tmux set-option -t "$SESSION" pane-border-status top
    tmux set-option -t "$SESSION" pane-border-format " #{pane_title} "
    tmux set-option -t "$SESSION" pane-border-style "fg=colour240"
    tmux set-option -t "$SESSION" pane-active-border-style "fg=colour26,bold"
}

action_shell_cmd() {
    local prompt_cmd
    # shellcheck disable=SC2016
    prompt_cmd='__harbor_demo_status=$?; printf "%s\n" "$__harbor_demo_status" > "$HARBOR_DEMO_STATUS_FILE"; __harbor_demo_marker=$(cat "$HARBOR_DEMO_MARKER_FILE" 2>/dev/null || true); if [ -n "$__harbor_demo_marker" ]; then tmux wait-for -S "$__harbor_demo_marker"; fi'
    join_cmd env \
        "HARBOR_DEMO_MARKER_FILE=$MARKER_FILE" \
        "HARBOR_DEMO_STATUS_FILE=$STATUS_FILE" \
        "PROMPT_COMMAND=$prompt_cmd" \
        "PS1=$ " \
        "HISTFILE=/dev/null" \
        bash --noprofile --norc
}

write_state_file() {
    STATE_FILE=$(mktemp "/tmp/${SESSION}-state-XXXXXX")
    DRIVER_FILE=$(mktemp "/tmp/${SESSION}-driver-XXXXXX.sh")

    {
        printf 'SESSION=%q\n' "$SESSION"
        printf 'WINDOW=%q\n' "$WINDOW"
        printf 'BACKEND=%q\n' "$BACKEND"
        printf 'MODEL=%q\n' "$MODEL"
        printf 'TOOL=%q\n' "$TOOL"
        printf 'TASK=%q\n' "$TASK"
        printf 'WEB_TASK=%q\n' "$WEB_TASK"
        printf 'STEP_DELAY=%q\n' "$STEP_DELAY"
        printf 'HOLD_DELAY=%q\n' "$HOLD_DELAY"
        printf 'TYPE_DELAY=%q\n' "$TYPE_DELAY"
        printf 'COMMAND_TIMEOUT=%q\n' "$COMMAND_TIMEOUT"
        printf 'NARRATIVE_PANE=%q\n' "$NARRATIVE_PANE"
        printf 'ACTION_PANE=%q\n' "$ACTION_PANE"
        printf 'NARRATIVE_FILE=%q\n' "$NARRATIVE_FILE"
        printf 'MARKER_FILE=%q\n' "$MARKER_FILE"
        printf 'STATUS_FILE=%q\n' "$STATUS_FILE"
    } > "$STATE_FILE"

    {
        printf '#!/usr/bin/env bash\n'
        printf 'exec bash %s --tmux-driver %s\n' "$(sq "$SCRIPT_PATH")" "$(sq "$STATE_FILE")"
    } > "$DRIVER_FILE"
    chmod +x "$DRIVER_FILE"
}

install_attach_hook() {
    tmux set-hook -t "$SESSION" client-attached "run-shell -b $(sq "$DRIVER_FILE")"
}

write_narrative_file() {
    local heading="$1"
    shift
    {
        printf '# %s\n\n' "$heading"
        local line
        for line in "$@"; do
            printf '%s\n' "$line"
        done
    } > "$NARRATIVE_FILE"
}

render_narrative() {
    tmux respawn-pane -k -t "$NARRATIVE_PANE" "$(narrative_pane_cmd)"
    tmux select-pane -t "$NARRATIVE_PANE" -T "Narrative"
}

show_card() {
    local title="$1"
    shift
    write_narrative_file "$title" "$@"
    render_narrative
}

show_step() {
    local step_num="$1" step_total="$2" title="$3"
    shift 3
    show_card "Step ${step_num}/${step_total}: ${title}" "$@"
}

clear_action() {
    tmux send-keys -t "$ACTION_PANE" C-l
}

show_action_heading() {
    local title="$1"
    tmux select-pane -t "$ACTION_PANE" -T "$title"
    tmux set-option -t "$SESSION" status-right " #[bg=colour28,fg=colour231] ${BACKEND} / $(tool_label "$TOOL") / ${title} #[default] "
}

narrative_render_cmd() {
    local glow_bin
    glow_bin=$(find_glow)
    if [ -n "$glow_bin" ]; then
        printf '%s --style dark --width 96 %s || cat %s' \
            "$(sq "$glow_bin")" \
            "$(sq "$NARRATIVE_FILE")" \
            "$(sq "$NARRATIVE_FILE")"
    else
        printf 'cat %s' "$(sq "$NARRATIVE_FILE")"
    fi
}

narrative_pane_cmd() {
    join_cmd bash --noprofile --norc -c "clear; $(narrative_render_cmd); sleep 86400"
}

type_text() {
    local text="$1"
    local i ch
    for ((i = 0; i < ${#text}; i++)); do
        ch="${text:$i:1}"
        tmux send-keys -t "$ACTION_PANE" -l "$ch"
        sleep "$TYPE_DELAY"
    done
}

type_and_run() {
    local cmd="$1"
    local marker="__HARBOR_WALKTHROUGH_DONE_${SESSION}_${RANDOM}_${RANDOM}__"
    local done_file waiter start now

    printf '%s\n' "$marker" > "$MARKER_FILE"
    done_file=$(mktemp "/tmp/${SESSION}-wait-XXXXXX")
    rm -f "$done_file"

    (
        tmux wait-for "$marker"
        : > "$done_file"
    ) &
    waiter=$!

    type_text "$cmd"
    tmux send-keys -t "$ACTION_PANE" C-m

    start=$(date +%s)
    while true; do
        if [ -e "$done_file" ]; then
            wait "$waiter" 2>/dev/null || true
            rm -f "$done_file"
            local status
            status=$(cat "$STATUS_FILE" 2>/dev/null || echo 0)
            : > "$MARKER_FILE"
            if [[ "$status" =~ ^[0-9]+$ ]]; then
                return "$status"
            fi
            return 0
        fi

        now=$(date +%s)
        if [ $((now - start)) -ge "$COMMAND_TIMEOUT" ]; then
            kill "$waiter" 2>/dev/null || true
            wait "$waiter" 2>/dev/null || true
            rm -f "$done_file"
            : > "$MARKER_FILE"
            warn "Timed out waiting for command marker: $marker"
            return 124
        fi

        sleep 0.2
    done
}

run_action_command() {
    local title="$1" cmd="$2" status
    show_action_heading "$title"
    if type_and_run "$cmd"; then
        return 0
    fi

    status=$?
    show_card "Demo stopped" \
        "The command for '${title}' exited with status ${status}." \
        "" \
        "The action pane shows the failing command and its output." \
        "Detach: Ctrl+b then d"
    return "$status"
}

pause() {
    sleep "$STEP_DELAY"
}

hold_capture() {
    sleep "$HOLD_DELAY"
}

show_intro() {
    show_card "Harbor launch walkthrough" \
        "harbor launch connects host coding tools to local" \
        "OpenAI-compatible Harbor backends." \
        "" \
        "Route in this walkthrough:" \
        "" \
        "  1. Inspect running Harbor services." \
        "  2. Generate adapter config for $(tool_label "$TOOL")." \
        "  3. Launch $(tool_label "$TOOL") directly against ${BACKEND}." \
        "  4. Add web tools through Boost and SearXNG." \
        "" \
        "Backend: ${BACKEND}" \
        "Tool: $(tool_label "$TOOL")" \
        "Model: ${MODEL:-auto-discover}"

    clear_action
    show_action_heading "Opening: Launch route"
    hold_capture
}

step1_status() {
    show_step 1 "$TOTAL_STEPS" "What's running?" \
        "First, inspect the current Harbor services." \
        "" \
        "The selected backend is '${BACKEND}'. If it was not already" \
        "running, this script started it before opening tmux."

    clear_action
    pause
    run_action_command "Step 1/4: Current Harbor services" "harbor ps"
    hold_capture
}

step2_config() {
    local cmd
    cmd=$(launch_cmd "" --config "$TOOL")

    show_step 2 "$TOTAL_STEPS" "Generate adapter config" \
        "Next, generate the adapter config for $(tool_label "$TOOL")." \
        "" \
        "Config mode writes or prints the host-tool settings without" \
        "starting the tool itself."

    clear_action
    pause
    run_action_command "Step 2/4: Config preview" "$cmd"
    hold_capture
}

step3_direct() {
    local planned cmd
    planned=$(direct_launch_cmd)
    cmd=$(action_cmd_for "$planned")

    show_step 3 "$TOTAL_STEPS" "Direct launch" \
        "Now launch $(tool_label "$TOOL") directly against ${BACKEND}." \
        "" \
        "harbor launch selects the backend URL, API key, and model," \
        "then starts the host tool." \
        "" \
        "Task: ${TASK}"

    clear_action
    pause
    run_action_command "Step 3/4: Direct launch" "$cmd"
    hold_capture
}

step4_web() {
    local planned cmd
    planned=$(web_launch_cmd)
    cmd=$(action_cmd_for "$planned")

    show_step 4 "$TOTAL_STEPS" "Web tools via Boost" \
        "Finally, add web tools with harbor launch --web." \
        "" \
        "The action pane first shows services before --web, then" \
        "runs the web launch, then shows services again so startup" \
        "is visible when Boost or SearXNG were not already running." \
        "" \
        "Task: ${WEB_TASK}"

    clear_action
    pause
    run_action_command "Step 4/4a: Before --web" "harbor ps"
    hold_capture
    run_action_command "Step 4/4b: Web-enabled launch" "$cmd"
    hold_capture
    run_action_command "Step 4/4c: After --web" "harbor ps"
    hold_capture
}

run_demo() {
    tmux set-hook -u -t "$SESSION" client-attached 2>/dev/null || true
    sleep 0.5

    show_intro
    step1_status
    step2_config
    step3_direct
    step4_web

    show_card "Demo complete" \
        "harbor launch connected $(tool_label "$TOOL") to ${BACKEND}" \
        "in three launch modes:" \
        "" \
        "  1. Config-only - generated adapter config" \
        "  2. Direct      - launched the host tool" \
        "  3. Web tools   - added Boost web tooling" \
        "" \
        "Detach: Ctrl+b then d" \
        "Stop Harbor: harbor down"
}

run_driver() {
    local state="$1"
    # shellcheck source=/dev/null
    source "$state"
    run_demo
}

main() {
    parse_args "$@"
    validate_config

    if [ "$DRY_RUN" = true ]; then
        print_dry_run
        return 0
    fi

    check_prereqs
    normalize_term_for_tmux
    ensure_backend

    echo
    log "Backend:         ${BACKEND}"
    log "Model:           ${MODEL:-auto-discover}"
    log "Tool:            ${TOOL} ($(tool_label "$TOOL"))"
    log "Direct task:     ${TASK}"
    log "Web task:        ${WEB_TASK}"
    log "Step delay:      ${STEP_DELAY}s"
    log "Hold delay:      ${HOLD_DELAY}s"
    log "Type delay:      ${TYPE_DELAY}s"
    log "Command timeout: ${COMMAND_TIMEOUT}s"
    log "Missing tool:    $([ "$ALLOW_MISSING_TOOL" = true ] && echo would-run || echo fail-fast)"
    echo

    if [ "$SKIP_PROMPT" = false ] && [ -t 0 ]; then
        read -r -p "Press Enter to open tmux and start the live walkthrough..."
    fi

    setup_tmux
    write_state_file
    install_attach_hook

    echo
    log "Attaching to tmux session: ${SESSION}"
    log "The demo starts after tmux attaches."
    log "Detach with Ctrl+b then d. Stop Harbor later with: harbor down"
    echo

    tmux attach-session -t "$SESSION"
}

if [ "${1:-}" = "--tmux-driver" ]; then
    [ -n "${2:-}" ] || err "Missing driver state file"
    run_driver "$2"
else
    main "$@"
fi
