#!/system/bin/sh
BASE=/data/local/codex-screen-toggle
echo $$ > "$BASE/adc.pid"
trap 'exit 0' TERM INT
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
        DOWN_US=$((0x$SEC * 1000000 + 0x$USEC))
        ;;
      00440001:00000000)
        if [ -n "$DOWN_US" ]; then
          DURATION_US=$((0x$SEC * 1000000 + 0x$USEC - DOWN_US))
          DOWN_US=
          if [ "$DURATION_US" -ge 600000 ]; then
            am start -a com.android.systemui.recents.TOGGLE_RECENTS -n com.android.systemui/.recents.RecentsActivity > /dev/null
            ACTION=RECENTS
          else
            input keyevent 23
            ACTION=CONFIRM
          fi
          echo "$(date '+%F %T') F10 -> $ACTION duration_us=$DURATION_US" >> "$BASE/events.log"
        fi
        ;;
    esac
  done
  sleep 1
done
