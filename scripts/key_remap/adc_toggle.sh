#!/system/bin/sh
# adc_toggle.sh - ADC physical key remap handler (F10 Confirm/Recents)
# Runs as root managed by supervisor.sh.

BASE=/data/local/codex-screen-toggle
STATE_DIR="$BASE/run"
mkdir -p "$STATE_DIR" 2>/dev/null
chmod 700 "$STATE_DIR" 2>/dev/null

LOCK_FILE="$STATE_DIR/adc_toggle.lock"
PID_FILE="$STATE_DIR/adc_toggle.pid"
LOG_FILE="$BASE/adc_toggle.log"
KEY_FIFO="$STATE_DIR/key.fifo"

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

if ! acquire_lock "$LOCK_FILE" "$BASE/adc_toggle.sh"; then
  EXISTING_PID=$(cat "$LOCK_FILE" 2>/dev/null)
  echo "$(date '+%F %T') [adc] Already active (PID $EXISTING_PID), exiting." >> "$LOG_FILE"
  exit 0
fi

echo $$ > "$PID_FILE"

cleanup() {
  pkill -P $$ 2>/dev/null
  rm -f "$LOCK_FILE" "$PID_FILE" /dev/c10h_f10.long 2>/dev/null
  exit 0
}
trap cleanup TERM INT EXIT

# Tuning: 0.35s hold threshold gives ~0.49s total instant response
F10_HOLD_SEC=0.35
F10_SEQ=0
F10_TIMER_PID=0

rm -f /dev/c10h_f10.long 2>/dev/null

# Dynamic sysfs device discovery (adc_keypad) with retry loop
find_adc_device() {
  for d in /sys/class/input/event*; do
    if [ -f "$d/device/name" ]; then
      local n
      n=$(cat "$d/device/name" 2>/dev/null)
      if [ "$n" = "adc_keypad" ]; then
        local ev
        ev=$(basename "$d" 2>/dev/null || echo "${d#/sys/class/input/}")
        if [ -c "/dev/input/$ev" ]; then
          echo "/dev/input/$ev"
          return 0
        fi
      fi
    fi
  done
  return 1
}

cleanup_orphan_readers() {
  local target_dev="$1"
  for p in /proc/[0-9]*; do
    local pid="${p#/proc/}"
    [ "$pid" != "$$" ] 2>/dev/null || continue
    if [ -f "$p/cmdline" ]; then
      local cmd
      cmd=$(tr '\000' ' ' < "$p/cmdline" 2>/dev/null)
      case "$cmd" in
        "$BASE/gpio_event_reader $target_dev"*)
          kill "$pid" 2>/dev/null
          ;;
      esac
    fi
  done
}

while true; do
  DEVICE=$(find_adc_device)
  if [ -z "$DEVICE" ]; then
    echo "$(date '+%F %T') [adc] Waiting for adc_keypad input device..." >> "$LOG_FILE"
    sleep 2
    continue
  fi

  echo "$(date '+%F %T') [adc] Starting event reader on $DEVICE" >> "$LOG_FILE"
  cleanup_orphan_readers "$DEVICE"

  "$BASE/gpio_event_reader" "$DEVICE" | while read SEC USEC TYPECODE VALUE; do
    case "$TYPECODE:$VALUE" in
      00440001:00000001)
        # F10 Down (Button 2 / Microphone: Confirm / Recents)
        F10_SEQ=$((F10_SEQ + 1))
        CUR_SEQ=$F10_SEQ
        rm -f /dev/c10h_f10.long 2>/dev/null
        (
          sleep $F10_HOLD_SEC
          if [ "x$CUR_SEQ" = "x$F10_SEQ" ]; then
            touch /dev/c10h_f10.long 2>/dev/null
            am start -a com.android.systemui.recents.TOGGLE_RECENTS -n com.android.systemui/.recents.RecentsActivity > /dev/null
            ( echo "$(date '+%F %T') F10 -> long-press (RECENTS) triggered" >> "$BASE/events.log" ) &
          fi
        ) &
        F10_TIMER_PID=$!
        ;;
      00440001:00000000)
        # F10 Up
        kill $F10_TIMER_PID 2>/dev/null
        if [ -f /dev/c10h_f10.long ]; then
          rm -f /dev/c10h_f10.long 2>/dev/null
        else
          # Instant microsecond CONFIRM key injection via uinput virtual device
          echo -n C > "$KEY_FIFO" 2>/dev/null || input keyevent 23
          ( echo "$(date '+%F %T') F10 -> short-press (CONFIRM)" >> "$BASE/events.log" ) &
        fi
        ;;
    esac
  done

  echo "$(date '+%F %T') [adc] Event reader disconnected, retrying..." >> "$LOG_FILE"
  sleep 1
done
