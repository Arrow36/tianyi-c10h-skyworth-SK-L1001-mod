#!/system/bin/sh
BASE=/data/local/codex-screen-toggle
mkdir -p /data/system/devices/idc /data/system/devices/keylayout
cp "$BASE/adc_keypad.idc" /data/system/devices/idc/adc_keypad.idc
cp "$BASE/codex_adc_keys.kl" /data/system/devices/keylayout/codex_adc_keys.kl
chmod 755 "$BASE/gpio_event_reader" "$BASE/adc_toggle.sh"
chmod 644 /data/system/devices/idc/adc_keypad.idc /data/system/devices/keylayout/codex_adc_keys.kl
restorecon -RF /data/system/devices
if [ -f "$BASE/adc.pid" ]; then
  OLD_PID=$(cat "$BASE/adc.pid")
  case "$(tr '\000' ' ' < /proc/$OLD_PID/cmdline 2>/dev/null)" in
    *codex-screen-toggle/adc_toggle.sh*)
      CHILD_PIDS=$(ps -A -o PID,PPID,ARGS | awk -v parent="$OLD_PID" '$2 == parent {print $1}')
      kill "$OLD_PID" 2>/dev/null
      for CHILD_PID in $CHILD_PIDS; do kill "$CHILD_PID" 2>/dev/null; done
      ;;
  esac
fi
echo adc_keypad > /sys/bus/platform/drivers/adc_keypad/unbind
echo adc_keypad > /sys/bus/platform/drivers/adc_keypad/bind
sleep 2
nohup /system/bin/sh "$BASE/adc_toggle.sh" > "$BASE/adc.log" 2>&1 < /dev/null &
sleep 1
if dumpsys input | grep -q 'KeyLayoutFile: /data/system/devices/keylayout/codex_adc_keys.kl'; then
  mv /data/system/devices/idc/adc_keypad.idc /data/system/devices/idc/adc_keypad.idc.runtime
  echo 'Confirm/recents key enabled for this boot.'
else
  echo 'ERROR: ADC input layout was not loaded.'
  exit 1
fi
