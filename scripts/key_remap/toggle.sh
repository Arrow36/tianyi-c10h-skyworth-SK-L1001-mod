#!/system/bin/sh
BASE=/data/local/codex-screen-toggle
echo $$ > "$BASE/runtime.pid"
trap 'exit 0' TERM INT
while true; do
  DEVICE=
  for NAMEFILE in /sys/class/input/event*/device/name; do
    [ "$(cat "$NAMEFILE" 2>/dev/null)" = gpio_keypad ] || continue
    EVENT=${NAMEFILE%/device/name}
    DEVICE=/dev/input/${EVENT##*/}
    break
  done
  if [ -z "$DEVICE" ]; then sleep 2; continue; fi
  "$BASE/gpio_event_reader" "$DEVICE" | while read SEC USEC TYPECODE VALUE; do
    case "$TYPECODE:$VALUE" in
      00740001:00000001)
        POWER_DOWN_US=$((0x$SEC * 1000000 + 0x$USEC))
        ;;
      00740001:00000000)
        if [ -n "$POWER_DOWN_US" ]; then
          DURATION_US=$((0x$SEC * 1000000 + 0x$USEC - POWER_DOWN_US))
          POWER_DOWN_US=
          if [ "$DURATION_US" -ge 600000 ]; then
            input keyevent --longpress 26
            ACTION="power-menu"
          else
            if [ "$(getprop sys.switch.screen)" = off ]; then
              input keyevent 224
              ACTION="screen-on"
            else
              input keyevent 223
              ACTION="screen-off"
            fi
          fi
          echo "$(date '+%F %T') power -> $ACTION duration_us=$DURATION_US" >> "$BASE/events.log"
        fi
        ;;
      00430001:00000001)
        F9_DOWN_US=$((0x$SEC * 1000000 + 0x$USEC))
        ;;
      00430001:00000000)
        if [ -n "$F9_DOWN_US" ]; then
          DURATION_US=$((0x$SEC * 1000000 + 0x$USEC - F9_DOWN_US))
          F9_DOWN_US=
          if [ "$DURATION_US" -ge 600000 ]; then
            am start -n com.dangbei.tvlauncher/com.dangbei.launcher.ui.main.MainActivity || input keyevent 3
            ACTION=HOME
          else
            input keyevent 4
            ACTION=BACK
          fi
          echo "$(date '+%F %T') F9 -> $ACTION duration_us=$DURATION_US" >> "$BASE/events.log"
        fi
        ;;
    esac
  done
  sleep 1
done
