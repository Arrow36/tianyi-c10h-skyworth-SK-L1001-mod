#!/system/bin/sh
# supervisor.sh - Single-instance process supervisor for C10H key remap daemons.
# Manages toggle.sh (GPIO Power/F9) and adc_toggle.sh (ADC F10).
# Runs as root with PPID 1 under init (telecom_shell).

BASE=/data/local/codex-screen-toggle
STATE_DIR="$BASE/run"
mkdir -p "$STATE_DIR" 2>/dev/null
chmod 700 "$STATE_DIR" 2>/dev/null

LOCK_DIR="$STATE_DIR/supervisor.lock"
PID_FILE="$STATE_DIR/supervisor.pid"

log_msg() {
  echo "$(date '+%F %T') [supervisor] $1" >> "$BASE/supervisor.log"
}

is_matching_proc() {
  local pid="$1"
  local expected="$2"
  [ -n "$pid" ] || return 1
  [ -d "/proc/$pid" ] || return 1
  local cmd
  cmd=$(tr '\000' ' ' < "/proc/$pid/cmdline" 2>/dev/null)
  case "$cmd" in
    *"$expected"*) return 0 ;;
    *) return 1 ;;
  esac
}

# 1. Acquire single-instance lock
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  EXISTING_PID=$(cat "$PID_FILE" 2>/dev/null)
  if is_matching_proc "$EXISTING_PID" "$BASE/supervisor.sh"; then
    log_msg "Supervisor already active (PID $EXISTING_PID), exiting."
    exit 0
  else
    log_msg "Stale supervisor lock found (PID $EXISTING_PID dead). Reclaiming."
    rm -rf "$LOCK_DIR" 2>/dev/null
    mkdir "$LOCK_DIR" 2>/dev/null || exit 1
  fi
fi

echo $$ > "$PID_FILE"
echo $$ > "$LOCK_DIR/pid"

cleanup() {
  log_msg "Supervisor exiting on signal."
  rm -rf "$LOCK_DIR" 2>/dev/null
  rm -f "$PID_FILE" 2>/dev/null
  exit 0
}
trap cleanup TERM INT

log_msg "Supervisor started (PID $$)."

# Log file rotation (keep under 200KB)
trim_log() {
  local log_file="$1"
  if [ -f "$log_file" ]; then
    local size
    size=$(wc -c < "$log_file" 2>/dev/null || echo 0)
    if [ "$size" -gt 204800 ]; then
      tail -n 500 "$log_file" > "$log_file.tmp" 2>/dev/null && mv "$log_file.tmp" "$log_file" 2>/dev/null
    fi
  fi
}

start_daemon() {
  local name="$1"
  local script="$BASE/$name.sh"
  local log="$BASE/$name.log"
  local pid_file="$STATE_DIR/$name.pid"

  local old_pid
  old_pid=$(cat "$pid_file" 2>/dev/null)
  if is_matching_proc "$old_pid" "$script"; then
    return 0
  fi

  log_msg "Starting daemon $name..."
  nohup /system/bin/sh "$script" >> "$log" 2>&1 < /dev/null &
  local new_pid=$!
  echo "$new_pid" > "$pid_file"
  log_msg "Daemon $name launched (PID $new_pid)."
}

# Main supervisor loop
RESTART_COUNT_TOGGLE=0
RESTART_COUNT_ADC=0
LAST_CHECK=$(date +%s 2>/dev/null || echo 0)

while true; do
  # Check toggle.sh
  TOGGLE_PID=$(cat "$STATE_DIR/toggle.pid" 2>/dev/null)
  if ! is_matching_proc "$TOGGLE_PID" "$BASE/toggle.sh"; then
    RESTART_COUNT_TOGGLE=$((RESTART_COUNT_TOGGLE + 1))
    start_daemon "toggle"
  fi

  # Check adc_toggle.sh
  ADC_PID=$(cat "$STATE_DIR/adc_toggle.pid" 2>/dev/null)
  if ! is_matching_proc "$ADC_PID" "$BASE/adc_toggle.sh"; then
    RESTART_COUNT_ADC=$((RESTART_COUNT_ADC + 1))
    start_daemon "adc_toggle"
  fi

  # Periodic log rotation every ~60s
  NOW=$(date +%s 2>/dev/null || echo 0)
  if [ $((NOW - LAST_CHECK)) -ge 60 ]; then
    trim_log "$BASE/supervisor.log"
    trim_log "$BASE/runtime.log"
    trim_log "$BASE/adc.log"
    trim_log "$BASE/events.log"
    LAST_CHECK=$NOW
  fi

  sleep 2
done
