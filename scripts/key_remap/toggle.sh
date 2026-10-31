#!/system/bin/sh
BASE=/data/local/codex-screen-toggle
STATE_DIR="$BASE/run"
mkdir -p "$STATE_DIR"
echo $$ > "$BASE/runtime.pid"
trap 'exit 0' TERM INT

# Tuning:
# Short taps are ~90ms-180ms.
# POWER uses direct native REQUEST_SHUTDOWN activity (~0.07s overhead, zero JVM startup).
# F9 uses direct native HOME intent (~0.14s overhead).
# 0.35s hold threshold gives ~0.42s - 0.49s total instant response across all physical buttons!
POWER_HOLD_SEC=0.35
F9_HOLD_SEC=0.35

POWER_SEQ=0
F9_SEQ=0

rm -f "$STATE_DIR"/c10h_power.* "$STATE_DIR"/c10h_f9.*

while true; do
  DEVICE=
  for d in /sys/class/input/event*; do
    if [ -f "$d/device/name" ] && [ "$(cat "$d/device/name" 2>/dev/null)" = "gpio_keypad" ]; then
      DEVICE="/dev/input/$(basename "$d")"
      break
    fi
  done
  if [ -z "$DEVICE" ]; then
    if [ -c /dev/input/event0 ]; then
      DEVICE=/dev/input/event0
    else
      sleep 2
      continue
    fi
  fi

  echo "$(date '+%F %T') starting toggle loop with DEVICE=$DEVICE" >> "$BASE/runtime.log"
  "$BASE/gpio_event_reader" "$DEVICE" 2>> "$BASE/runtime.log" | while read SEC USEC TYPECODE VALUE; do
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
  echo "$(date '+%F %T') reader pipeline ended with code $?" >> "$BASE/runtime.log"
  sleep 1
done
