#!/system/bin/sh
BASE=/data/local/codex-screen-toggle
echo $$ > "$BASE/adc.pid"
trap 'exit 0' TERM INT

# Tuning: 0.35s hold threshold gives ~0.49s total instant response
F10_HOLD_SEC=0.35
F10_SEQ=0

rm -f /dev/c10h_f10.*

while true; do
  DEVICE=
  for NAMEFILE in /sys/class/input/event*/device/name; do
    [ "$(cat "$NAMEFILE" 2>/dev/null)" = adc_keypad ] || continue
    EVENT=${NAMEFILE%/device/name}
    DEVICE=/dev/input/${EVENT##*/}
    break
  done
  if [ -z "$DEVICE" ]; then sleep 2; continue; fi

  "$BASE/gpio_event_reader" "$DEVICE" | while read SEC USEC TYPECODE VALUE; do
    case "$TYPECODE:$VALUE" in
      00440001:00000001)
        # F10 Down (Button 2 / Microphone: Confirm / Recents)
        F10_SEQ=$((F10_SEQ + 1))
        CUR_SEQ=$F10_SEQ
        echo "$CUR_SEQ" > /dev/c10h_f10.down
        (
          sleep $F10_HOLD_SEC
          if [ "x$(cat /dev/c10h_f10.down 2>/dev/null)" = "x$CUR_SEQ" ]; then
            touch /dev/c10h_f10.long
            am start -a com.android.systemui.recents.TOGGLE_RECENTS -n com.android.systemui/.recents.RecentsActivity > /dev/null
            echo "$(date '+%F %T') F10 -> long-press (RECENTS) triggered" >> "$BASE/events.log"
          fi
        ) &
        ;;
      00440001:00000000)
        # F10 Up
        rm -f /dev/c10h_f10.down
        if [ -f /dev/c10h_f10.long ]; then
          rm -f /dev/c10h_f10.long
        else
          input keyevent 23
          echo "$(date '+%F %T') F10 -> short-press (CONFIRM)" >> "$BASE/events.log"
        fi
        ;;
    esac
  done
  sleep 1
done
