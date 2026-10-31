#!/system/bin/sh
# adc_toggle.sh - ADC physical key remap handler (F10 Confirm/Recents)
# Runs as root managed by supervisor.sh.

BASE=/data/local/codex-screen-toggle
STATE_DIR="$BASE/run"
mkdir -p "$STATE_DIR" 2>/dev/null
chmod 700 "$STATE_DIR" 2>/dev/null

LOCK_DIR="$STATE_DIR/adc_toggle.lock"
PID_FILE="$STATE_DIR/adc_toggle.pid"

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

# Single-instance lock
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  EXISTING_PID=$(cat "$PID_FILE" 2>/dev/null)
  if is_matching_proc "$EXISTING_PID" "$BASE/adc_toggle.sh" && [ "$EXISTING_PID" != "$$" ]; then
    echo "$(date '+%F %T') [adc] Already running with PID $EXISTING_PID, exiting."
    exit 0
  fi
  rm -rf "$LOCK_DIR" 2>/dev/null
  mkdir "$LOCK_DIR" 2>/dev/null || exit 1
fi

echo $$ > "$PID_FILE"
echo $$ > "$LOCK_DIR/pid"

cleanup() {
  pkill -P $$ 2>/dev/null
  rm -rf "$LOCK_DIR" 2>/dev/null
  rm -f "$PID_FILE" 2>/dev/null
  exit 0
}
trap cleanup TERM INT EXIT

# Tuning: 0.35s hold threshold gives ~0.49s total instant response
F10_HOLD_SEC=0.35
F10_SEQ=0

rm -f "$STATE_DIR"/c10h_f10.*

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

while true; do
  DEVICE=$(find_adc_device)
  if [ -z "$DEVICE" ]; then
    echo "$(date '+%F %T') [adc] Waiting for adc_keypad input device..." >> "$BASE/adc.log"
    sleep 2
    continue
  fi

  echo "$(date '+%F %T') [adc] Starting event reader on $DEVICE" >> "$BASE/adc.log"
  for old_r in $(pgrep -f "gpio_event_reader $DEVICE" 2>/dev/null); do
    kill "$old_r" 2>/dev/null
  done
  "$BASE/gpio_event_reader" "$DEVICE" | while read SEC USEC TYPECODE VALUE; do
    case "$TYPECODE:$VALUE" in
      00440001:00000001)
        # F10 Down (Button 2 / Microphone: Confirm / Recents)
        F10_SEQ=$((F10_SEQ + 1))
        CUR_SEQ=$F10_SEQ
        echo "$CUR_SEQ" > "$STATE_DIR/c10h_f10.down"
        (
          sleep $F10_HOLD_SEC
          if [ "x$(cat "$STATE_DIR/c10h_f10.down" 2>/dev/null)" = "x$CUR_SEQ" ]; then
            touch "$STATE_DIR/c10h_f10.long"
            am start -a com.android.systemui.recents.TOGGLE_RECENTS -n com.android.systemui/.recents.RecentsActivity > /dev/null
            echo "$(date '+%F %T') F10 -> long-press (RECENTS) triggered" >> "$BASE/events.log"
          fi
        ) &
        ;;
      00440001:00000000)
        # F10 Up
        rm -f "$STATE_DIR/c10h_f10.down"
        if [ -f "$STATE_DIR/c10h_f10.long" ]; then
          rm -f "$STATE_DIR/c10h_f10.long"
        else
          input keyevent 23
          echo "$(date '+%F %T') F10 -> short-press (CONFIRM)" >> "$BASE/events.log"
        fi
        ;;
    esac
  done

  echo "$(date '+%F %T') [adc] Event reader disconnected, retrying..." >> "$BASE/adc.log"
  sleep 1
done
