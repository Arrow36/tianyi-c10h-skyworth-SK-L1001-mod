#!/system/bin/sh
BASE=/data/local/codex-screen-toggle
STATE_DIR="$BASE/run"
mkdir -p "$STATE_DIR" /data/system/devices/idc /data/system/devices/keylayout 2>/dev/null
chmod 777 "$STATE_DIR" 2>/dev/null

cp "$BASE/adc_keypad.idc" /data/system/devices/idc/adc_keypad.idc 2>/dev/null
cp "$BASE/codex_adc_keys.kl" /data/system/devices/keylayout/codex_adc_keys.kl 2>/dev/null
chmod 755 "$BASE/gpio_event_reader" "$BASE/adc_toggle.sh" 2>/dev/null
chmod 666 /data/system/devices/idc/adc_keypad.idc /data/system/devices/keylayout/codex_adc_keys.kl 2>/dev/null
restorecon -RF /data/system/devices 2>/dev/null

if ! dumpsys input | grep -q 'KeyLayoutFile: /data/system/devices/keylayout/codex_adc_keys.kl'; then
  if [ -w /sys/bus/platform/drivers/adc_keypad/unbind ]; then
    echo adc_keypad > /sys/bus/platform/drivers/adc_keypad/unbind
    echo adc_keypad > /sys/bus/platform/drivers/adc_keypad/bind
    sleep 2
  fi
fi

if [ -f "$BASE/adc.pid" ]; then
  OLD_PID=$(cat "$BASE/adc.pid" 2>/dev/null)
  if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    CHILD_PIDS=$(ps -A -o PID,PPID,ARGS | awk -v parent="$OLD_PID" '$2 == parent {print $1}')
    kill "$OLD_PID" 2>/dev/null
    for CHILD_PID in $CHILD_PIDS; do kill "$CHILD_PID" 2>/dev/null; done
  fi
fi

nohup /system/bin/sh "$BASE/adc_toggle.sh" > "$BASE/adc.log" 2>&1 < /dev/null &

