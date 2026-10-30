#!/system/bin/sh
BASE=/data/local/codex-screen-toggle
echo $$ > "$BASE/runtime.pid"
trap 'exit 0' TERM INT

HOLD_SEC=0.5
POWER_SEQ=0
F9_SEQ=0

rm -f /dev/c10h_power.* /dev/c10h_f9.*

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
        # Power Down
        POWER_SEQ=$((POWER_SEQ + 1))
        CUR_SEQ=$POWER_SEQ
        echo "$CUR_SEQ" > /dev/c10h_power.down
        (
          sleep $HOLD_SEC
          if [ "x$(cat /dev/c10h_power.down 2>/dev/null)" = "x$CUR_SEQ" ]; then
            touch /dev/c10h_power.long
            input keyevent --longpress 26
            echo "$(date '+%F %T') power -> long-press (power-menu) triggered" >> "$BASE/events.log"
          fi
        ) &
        ;;
      00740001:00000000)
        # Power Up
        rm -f /dev/c10h_power.down
        if [ -f /dev/c10h_power.long ]; then
          rm -f /dev/c10h_power.long
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
        echo "$CUR_SEQ" > /dev/c10h_f9.down
        (
          sleep $HOLD_SEC
          if [ "x$(cat /dev/c10h_f9.down 2>/dev/null)" = "x$CUR_SEQ" ]; then
            touch /dev/c10h_f9.long
            am start -a android.intent.action.MAIN -c android.intent.category.HOME || input keyevent 3
            echo "$(date '+%F %T') F9 -> long-press (HOME) triggered" >> "$BASE/events.log"
          fi
        ) &
        ;;
      00430001:00000000)
        # F9 Up
        rm -f /dev/c10h_f9.down
        if [ -f /dev/c10h_f9.long ]; then
          rm -f /dev/c10h_f9.long
        else
          input keyevent 4
          echo "$(date '+%F %T') F9 -> short-press (BACK)" >> "$BASE/events.log"
        fi
        ;;
    esac
  done
  sleep 1
done
