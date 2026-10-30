#!/system/bin/sh
BASE=/data/local/codex-screen-toggle
mkdir -p /data/system/devices/idc /data/system/devices/keylayout
cp "$BASE/gpio_keypad.idc" /data/system/devices/idc/gpio_keypad.idc
cp "$BASE/codex_gpio_sleep.kl" /data/system/devices/keylayout/codex_gpio_sleep.kl
chmod 755 /data/system/devices /data/system/devices/idc /data/system/devices/keylayout
chmod 644 /data/system/devices/idc/gpio_keypad.idc /data/system/devices/keylayout/codex_gpio_sleep.kl
restorecon -RF /data/system/devices
chmod 755 "$BASE/gpio_event_reader" "$BASE/toggle.sh"
if [ -f "$BASE/runtime.pid" ]; then
  OLD_PID=$(cat "$BASE/runtime.pid")
  case "$(tr '\000' ' ' < /proc/$OLD_PID/cmdline 2>/dev/null)" in
    *codex-screen-toggle/toggle.sh*)
      CHILD_PIDS=$(ps -A -o PID,PPID,ARGS | awk -v parent="$OLD_PID" '$2 == parent {print $1}')
      kill "$OLD_PID" 2>/dev/null
      for CHILD_PID in $CHILD_PIDS; do kill "$CHILD_PID" 2>/dev/null; done
      ;;
  esac
fi
echo gpio_keypad > /sys/bus/platform/drivers/gpio-keypad/unbind
echo gpio_keypad > /sys/bus/platform/drivers/gpio-keypad/bind
# Wait for ueventd to recreate /dev/input/event0 before opening it.
sleep 2
nohup /system/bin/sh "$BASE/toggle.sh" > "$BASE/runtime.log" 2>&1 < /dev/null &
sleep 1
# Android has loaded the layout into memory. Disable boot selection so a reboot
# without the runtime listener falls back to the original vendor key behavior.
if dumpsys input | grep -q 'KeyLayoutFile: /data/system/devices/keylayout/codex_gpio_sleep.kl'; then
  mv /data/system/devices/idc/gpio_keypad.idc /data/system/devices/idc/gpio_keypad.idc.runtime
  echo 'Screen toggle enabled for this boot. Reboot restores original key behavior.'
else
  echo 'ERROR: input layout was not loaded.'
  exit 1
fi

/system/bin/sh "$BASE/activate_adc.sh"
