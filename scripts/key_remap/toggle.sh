#!/system/bin/sh
# toggle.sh - GPIO physical key remap handler (Power & F9)
# Runs as root managed by supervisor.sh.

BASE=/data/local/codex-screen-toggle
STATE_DIR="$BASE/run"
mkdir -p "$STATE_DIR" 2>/dev/null
chmod 700 "$STATE_DIR" 2>/dev/null

LOCK_DIR="$STATE_DIR/toggle.lock"
PID_FILE="$STATE_DIR/toggle.pid"

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
  if is_matching_proc "$EXISTING_PID" "$BASE/toggle.sh" && [ "$EXISTING_PID" != "$$" ]; then
    echo "$(date '+%F %T') [toggle] Already running with PID $EXISTING_PID, exiting."
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

# Tuning:
# 0.35s hold threshold gives ~0.42s - 0.49s instant response.
# Power long-press calls vendor-customized ShutdownActivity (dual-option dialog with Shutdown & Reboot).
# F9 long-press calls standard AOSP HOME intent.
POWER_HOLD_SEC=0.35
F9_HOLD_SEC=0.35

POWER_SEQ=0
F9_SEQ=0

rm -f "$STATE_DIR"/c10h_power.* "$STATE_DIR"/c10h_f9.*

# Dynamic sysfs device discovery (gpio_keypad) with retry loop
find_gpio_device() {
  for d in /sys/class/input/event*; do
    if [ -f "$d/device/name" ]; then
      local n
      n=$(cat "$d/device/name" 2>/dev/null)
      if [ "$n" = "gpio_keypad" ]; then
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
  DEVICE=$(find_gpio_device)
  if [ -z "$DEVICE" ]; then
    echo "$(date '+%F %T') [toggle] Waiting for gpio_keypad input device..." >> "$BASE/runtime.log"
    sleep 2
    continue
  fi

  echo "$(date '+%F %T') [toggle] Starting event reader on $DEVICE" >> "$BASE/runtime.log"
  for old_r in $(pgrep -f "gpio_event_reader $DEVICE" 2>/dev/null); do
    kill "$old_r" 2>/dev/null
  done
  "$BASE/gpio_event_reader" "$DEVICE" | while read SEC USEC TYPECODE VALUE; do
    case "$TYPECODE:$VALUE" in
      00740001:00000001)
        # Power Down
        POWER_SEQ=$((POWER_SEQ + 1))
        CUR_SEQ=$POWER_SEQ
        echo "$CUR_SEQ" > "$STATE_DIR/c10h_power.down"
        (
          sleep $POWER_HOLD_SEC
          if [ "x$(cat "$STATE_DIR/c10h_power.down" 2>/dev/null)" = "x$CUR_SEQ" ]; then
            touch "$STATE_DIR/c10h_power.long"
            # Skyworth C10H custom ShutdownActivity: displays dual-option prompt with Reboot & Shutdown
            am start -a com.android.internal.intent.action.REQUEST_SHUTDOWN --ez android.intent.extra.KEY_CONFIRM true > /dev/null 2>&1 || input keyevent --longpress 26
            echo "$(date '+%F %T') power -> long-press (power-menu) triggered" >> "$BASE/events.log"
          fi
        ) &
        ;;
      00740001:00000000)
        # Power Up
        rm -f "$STATE_DIR/c10h_power.down"
        if [ -f "$STATE_DIR/c10h_power.long" ]; then
          rm -f "$STATE_DIR/c10h_power.long"
        else
          if [ "$(getprop sys.switch.screen)" = off ]; then
            input keyevent 224
            ACTION="screen-on"
          else
            input keyevent 223
            ACTION="screen-off"
          fi
          echo "$(date '+%F %T') power -> short-press ($ACTION)" >> "$BASE/events.log"
        fi
        ;;
      00430001:00000001)
        # F9 Down (Button 1: Back / Home)
        F9_SEQ=$((F9_SEQ + 1))
        CUR_SEQ=$F9_SEQ
        echo "$CUR_SEQ" > "$STATE_DIR/c10h_f9.down"
        (
          sleep $F9_HOLD_SEC
          if [ "x$(cat "$STATE_DIR/c10h_f9.down" 2>/dev/null)" = "x$CUR_SEQ" ]; then
            touch "$STATE_DIR/c10h_f9.long"
            am start -a android.intent.action.MAIN -c android.intent.category.HOME || input keyevent 3
            echo "$(date '+%F %T') F9 -> long-press (HOME) triggered" >> "$BASE/events.log"
          fi
        ) &
        ;;
      00430001:00000000)
        # F9 Up
        rm -f "$STATE_DIR/c10h_f9.down"
        if [ -f "$STATE_DIR/c10h_f9.long" ]; then
          rm -f "$STATE_DIR/c10h_f9.long"
        else
          input keyevent 4
          echo "$(date '+%F %T') F9 -> short-press (BACK)" >> "$BASE/events.log"
        fi
        ;;
    esac
  done

  echo "$(date '+%F %T') [toggle] Event reader disconnected, retrying..." >> "$BASE/runtime.log"
  sleep 1
done
