#!/system/bin/sh
BASE=/data/local/codex-screen-toggle
STATE_DIR="$BASE/run"
mkdir -p "$STATE_DIR"
echo $$ > "$BASE/adc.pid"
trap 'exit 0' TERM INT

# Tuning: 0.35s hold threshold gives ~0.49s total instant response
F10_HOLD_SEC=0.35
F10_SEQ=0

rm -f "$STATE_DIR"/c10h_f10.*

while true; do
  DEVICE=
  for d in /sys/class/input/event*; do
    if [ -f "$d/device/name" ] && [ "$(cat "$d/device/name" 2>/dev/null)" = "adc_keypad" ]; then
      DEVICE="/dev/input/$(basename "$d")"
      break
    fi
  done
  if [ -z "$DEVICE" ]; then
    if [ -c /dev/input/event6 ]; then
      DEVICE=/dev/input/event6
    else
      sleep 2
      continue
    fi
  fi

  echo "$(date '+%F %T') starting adc loop with DEVICE=$DEVICE" >> "$BASE/adc.log"
  "$BASE/gpio_event_reader" "$DEVICE" 2>> "$BASE/adc.log" | while read SEC USEC TYPECODE VALUE; do
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
  echo "$(date '+%F %T') adc reader pipeline ended with code $?" >> "$BASE/adc.log"
  sleep 1
done
