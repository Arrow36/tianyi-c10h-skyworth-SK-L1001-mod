#!/system/bin/sh
trap '' HUP
BASE=/data/local/codex-screen-toggle
STATE_DIR="$BASE/run"
mkdir -p "$STATE_DIR" /data/system/devices/idc /data/system/devices/keylayout 2>/dev/null
chmod 777 "$STATE_DIR" 2>/dev/null

# Fix Home key dispatch crash: stock build.prop points epg.launcher.packagename to debloated TMC,
# causing PhoneWindowManager.startDockOrHome to throw NullPointerException and lag 1-2 seconds.
setprop epg.launcher.packagename com.dangbei.tvlauncher
setprop sys.deflauncher.pkg com.dangbei.tvlauncher
setprop sys.deflauncher.cls com.dangbei.launcher.ui.main.MainActivity

# 1. Kill old daemons if any and launch toggle.sh IMMEDIATELY
if [ -f "$BASE/runtime.pid" ]; then
  OLD_PID=$(cat "$BASE/runtime.pid" 2>/dev/null)
  if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    CHILD_PIDS=$(ps -A -o PID,PPID,ARGS | awk -v parent="$OLD_PID" '$2 == parent {print $1}')
    kill "$OLD_PID" 2>/dev/null
    for CHILD_PID in $CHILD_PIDS; do kill "$CHILD_PID" 2>/dev/null; done
  fi
fi
nohup /system/bin/sh "$BASE/toggle.sh" > "$BASE/runtime.log" 2>&1 < /dev/null &

# 2. Launch adc_toggle.sh IMMEDIATELY
if [ -f "$BASE/adc.pid" ]; then
  OLD_PID=$(cat "$BASE/adc.pid" 2>/dev/null)
  if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    CHILD_PIDS=$(ps -A -o PID,PPID,ARGS | awk -v parent="$OLD_PID" '$2 == parent {print $1}')
    kill "$OLD_PID" 2>/dev/null
    for CHILD_PID in $CHILD_PIDS; do kill "$CHILD_PID" 2>/dev/null; done
  fi
fi
nohup /system/bin/sh "$BASE/adc_toggle.sh" > "$BASE/adc.log" 2>&1 < /dev/null &

# 3. Background maintenance tasks (ensure IDC files and permissions)
(
  cp "$BASE/gpio_keypad.idc" /data/system/devices/idc/gpio_keypad.idc 2>/dev/null
  cp "$BASE/adc_keypad.idc" /data/system/devices/idc/adc_keypad.idc 2>/dev/null
  cp "$BASE/codex_gpio_sleep.kl" /data/system/devices/keylayout/codex_gpio_sleep.kl 2>/dev/null
  cp "$BASE/codex_adc_keys.kl" /data/system/devices/keylayout/codex_adc_keys.kl 2>/dev/null
  chmod 777 /data/system/devices /data/system/devices/idc /data/system/devices/keylayout 2>/dev/null
  chmod 666 /data/system/devices/idc/*.idc /data/system/devices/keylayout/*.kl 2>/dev/null
  restorecon -RF /data/system/devices 2>/dev/null
  chmod 755 "$BASE/gpio_event_reader" "$BASE/toggle.sh" "$BASE/adc_toggle.sh" 2>/dev/null

  if ! dumpsys input | grep -q 'KeyLayoutFile: /data/system/devices/keylayout/codex_gpio_sleep.kl'; then
    if [ -w /sys/bus/platform/drivers/gpio-keypad/unbind ]; then
      echo gpio_keypad > /sys/bus/platform/drivers/gpio-keypad/unbind
      echo gpio_keypad > /sys/bus/platform/drivers/gpio-keypad/bind
    fi
  fi

  if ! dumpsys input | grep -q 'KeyLayoutFile: /data/system/devices/keylayout/codex_adc_keys.kl'; then
    if [ -w /sys/bus/platform/drivers/adc_keypad/unbind ]; then
      echo adc_keypad > /sys/bus/platform/drivers/adc_keypad/unbind
      echo adc_keypad > /sys/bus/platform/drivers/adc_keypad/bind
    fi
  fi

  pm disable com.dangbei.tvlauncher/com.dangbei.launcher.service.HomeKeyEventCatchService >/dev/null 2>&1
  am start-service -n dev.vodik7.atvtoolsserver/.Service >/dev/null 2>&1
) &


