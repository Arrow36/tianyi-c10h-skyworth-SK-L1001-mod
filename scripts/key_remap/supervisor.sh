#!/system/bin/sh
# supervisor.sh - Single-instance process supervisor for C10H key remap daemons.
# Manages uinput_injector (instant key injector), toggle.sh (GPIO Power/F9), and adc_toggle.sh (ADC F10).
# Runs as root with PPID 1 under init (telecom_shell).

BASE=/data/local/codex-screen-toggle
STATE_DIR="$BASE/run"
mkdir -p "$STATE_DIR" 2>/dev/null
chmod 700 "$STATE_DIR" 2>/dev/null

LOCK_FILE="$STATE_DIR/supervisor.lock"
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

# 1. Acquire atomic single-instance lock via hard link
acquire_lock() {
  local lockfile="$1"
  local cmd_match="$2"
  local tmpfile="${lockfile}.tmp.$$"
  local max_attempts=5
  local attempt=0

  echo $$ > "$tmpfile"
  while [ "$attempt" -lt "$max_attempts" ]; do
    attempt=$((attempt + 1))
    if ln "$tmpfile" "$lockfile" 2>/dev/null; then
      rm -f "$tmpfile"
      return 0
    fi

    local existing_pid
    existing_pid=$(cat "$lockfile" 2>/dev/null)
    if is_matching_proc "$existing_pid" "$cmd_match"; then
      rm -f "$tmpfile"
      if [ "$existing_pid" = "$$" ]; then
        return 0
      fi
      return 1
    fi

    local reclaim_file="${lockfile}.reclaim.$$"
    if mv "$lockfile" "$reclaim_file" 2>/dev/null; then
      rm -f "$reclaim_file"
      continue
    fi

    sleep 0.1 2>/dev/null || sleep 1
  done

  rm -f "$tmpfile"
  return 1
}

if ! acquire_lock "$LOCK_FILE" "$BASE/supervisor.sh"; then
  EXISTING_PID=$(cat "$LOCK_FILE" 2>/dev/null)
  log_msg "Supervisor already active (PID $EXISTING_PID), exiting."
  exit 0
fi

echo $$ > "$PID_FILE"

# Ensure communication FIFO exists for microsecond key injection
[ -p "$STATE_DIR/key.fifo" ] || mkfifo "$STATE_DIR/key.fifo" 2>/dev/null
chmod 600 "$STATE_DIR/key.fifo" 2>/dev/null

cleanup() {
  log_msg "Supervisor exiting on signal."
  rm -f "$LOCK_FILE" "$PID_FILE" "$STATE_DIR/key.fifo" 2>/dev/null
  exit 0
}
trap cleanup TERM INT

log_msg "Supervisor started (PID $$)."

# In-place log file rotation (preserves open file descriptors & inodes)
trim_log() {
  local log_file="$1"
  if [ -f "$log_file" ]; then
    local size
    size=$(wc -c < "$log_file" 2>/dev/null || echo 0)
    if [ "$size" -gt 204800 ]; then
      local tmp="${log_file}.tmp.$$"
      if tail -c 51200 "$log_file" > "$tmp" 2>/dev/null; then
        cat "$tmp" > "$log_file" 2>/dev/null
        rm -f "$tmp" 2>/dev/null
      fi
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

start_uinput_injector() {
  local bin="$BASE/uinput_injector"
  local pid_file="$STATE_DIR/uinput_injector.pid"
  [ -x "$bin" ] || return 1

  local old_pid
  old_pid=$(cat "$pid_file" 2>/dev/null)
  if is_matching_proc "$old_pid" "$bin"; then
    return 0
  fi

  log_msg "Starting uinput_injector daemon..."
  nohup "$bin" > /dev/null 2>&1 < /dev/null &
  local new_pid=$!
  echo "$new_pid" > "$pid_file"
  log_msg "uinput_injector launched (PID $new_pid)."
}

# Main supervisor loop with crash backoff throttling
FAIL_COUNT_TOGGLE=0
FAIL_COUNT_ADC=0
FAIL_COUNT_UINPUT=0
LAST_START_TOGGLE=0
LAST_START_ADC=0
LAST_START_UINPUT=0
LAST_CHECK=$(date +%s 2>/dev/null || echo 0)

while true; do
  NOW=$(date +%s 2>/dev/null || echo 0)

  # Check uinput_injector (hardware uinput virtual keyboard)
  UINJ_PID=$(cat "$STATE_DIR/uinput_injector.pid" 2>/dev/null)
  if is_matching_proc "$UINJ_PID" "$BASE/uinput_injector"; then
    if [ "$LAST_START_UINPUT" -gt 0 ] && [ $((NOW - LAST_START_UINPUT)) -ge 60 ]; then
      FAIL_COUNT_UINPUT=0
    fi
  else
    FAIL_COUNT_UINPUT=$((FAIL_COUNT_UINPUT + 1))
    if [ "$FAIL_COUNT_UINPUT" -le 5 ]; then
      start_uinput_injector
      LAST_START_UINPUT=$(date +%s 2>/dev/null || echo 0)
    fi
  fi

  # Check toggle.sh
  TOGGLE_PID=$(cat "$STATE_DIR/toggle.pid" 2>/dev/null)
  if is_matching_proc "$TOGGLE_PID" "$BASE/toggle.sh"; then
    if [ "$LAST_START_TOGGLE" -gt 0 ] && [ $((NOW - LAST_START_TOGGLE)) -ge 60 ]; then
      if [ "$FAIL_COUNT_TOGGLE" -gt 0 ]; then
        log_msg "Daemon toggle has stabilized; resetting failure counter."
        FAIL_COUNT_TOGGLE=0
      fi
    fi
  else
    FAIL_COUNT_TOGGLE=$((FAIL_COUNT_TOGGLE + 1))
    log_msg "Daemon toggle down (crash count: $FAIL_COUNT_TOGGLE)."
    if [ "$FAIL_COUNT_TOGGLE" -gt 5 ]; then
      log_msg "WARNING: Daemon toggle crashing rapidly. Applying 15s backoff delay."
      sleep 15
    elif [ "$FAIL_COUNT_TOGGLE" -gt 3 ]; then
      log_msg "Daemon toggle restart throttled. Applying 5s backoff delay."
      sleep 5
    fi
    start_daemon "toggle"
    LAST_START_TOGGLE=$(date +%s 2>/dev/null || echo 0)
  fi

  # Check adc_toggle.sh
  ADC_PID=$(cat "$STATE_DIR/adc_toggle.pid" 2>/dev/null)
  if is_matching_proc "$ADC_PID" "$BASE/adc_toggle.sh"; then
    if [ "$LAST_START_ADC" -gt 0 ] && [ $((NOW - LAST_START_ADC)) -ge 60 ]; then
      if [ "$FAIL_COUNT_ADC" -gt 0 ]; then
        log_msg "Daemon adc_toggle has stabilized; resetting failure counter."
        FAIL_COUNT_ADC=0
      fi
    fi
  else
    FAIL_COUNT_ADC=$((FAIL_COUNT_ADC + 1))
    log_msg "Daemon adc_toggle down (crash count: $FAIL_COUNT_ADC)."
    if [ "$FAIL_COUNT_ADC" -gt 5 ]; then
      log_msg "WARNING: Daemon adc_toggle crashing rapidly. Applying 15s backoff delay."
      sleep 15
    elif [ "$FAIL_COUNT_ADC" -gt 3 ]; then
      log_msg "Daemon adc_toggle restart throttled. Applying 5s backoff delay."
      sleep 5
    fi
    start_daemon "adc_toggle"
    LAST_START_ADC=$(date +%s 2>/dev/null || echo 0)
  fi

  # Periodic log rotation every ~60s
  NOW=$(date +%s 2>/dev/null || echo 0)
  if [ $((NOW - LAST_CHECK)) -ge 60 ]; then
    trim_log "$BASE/supervisor.log"
    trim_log "$BASE/toggle.log"
    trim_log "$BASE/adc_toggle.log"
    trim_log "$BASE/events.log"
    # Retire legacy log files if present
    rm -f "$BASE/runtime.log" "$BASE/adc.log" 2>/dev/null
    LAST_CHECK=$NOW
  fi

  sleep 2
done
