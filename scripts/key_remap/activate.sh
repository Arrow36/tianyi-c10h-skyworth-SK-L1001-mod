#!/system/bin/sh
# activate.sh - Key remap system activator
# Invoked at boot by init via telecom_shell (as root, PPID 1).

trap '' HUP
BASE=/data/local/codex-screen-toggle
STATE_DIR="$BASE/run"

# 1. Enforce strict directory and file permissions (Principle of Least Privilege)
mkdir -p "$STATE_DIR" /data/system/devices/idc /data/system/devices/keylayout 2>/dev/null
chown -R root:root "$BASE" 2>/dev/null
chmod 755 "$BASE" 2>/dev/null
chmod 700 "$STATE_DIR" 2>/dev/null
chmod 755 "$BASE"/*.sh "$BASE/gpio_event_reader" 2>/dev/null

# 2. Deploy IDC and KeyLayout files permanently for native InputReader loading
cp "$BASE/gpio_keypad.idc" /data/system/devices/idc/gpio_keypad.idc 2>/dev/null
cp "$BASE/adc_keypad.idc" /data/system/devices/idc/adc_keypad.idc 2>/dev/null
cp "$BASE/codex_gpio_sleep.kl" /data/system/devices/keylayout/codex_gpio_sleep.kl 2>/dev/null
cp "$BASE/codex_adc_keys.kl" /data/system/devices/keylayout/codex_adc_keys.kl 2>/dev/null
chmod 755 /data/system/devices /data/system/devices/idc /data/system/devices/keylayout 2>/dev/null
chown root:root /data/system/devices/idc/gpio_keypad.idc \
                /data/system/devices/idc/adc_keypad.idc \
                /data/system/devices/keylayout/codex_gpio_sleep.kl \
                /data/system/devices/keylayout/codex_adc_keys.kl 2>/dev/null
chmod 644 /data/system/devices/idc/gpio_keypad.idc \
          /data/system/devices/idc/adc_keypad.idc \
          /data/system/devices/keylayout/codex_gpio_sleep.kl \
          /data/system/devices/keylayout/codex_adc_keys.kl 2>/dev/null
restorecon -RF /data/system/devices 2>/dev/null

# 3. System property fix for Home key dispatch
setprop epg.launcher.packagename com.dangbei.tvlauncher
setprop sys.deflauncher.pkg com.dangbei.tvlauncher
setprop sys.deflauncher.cls com.dangbei.launcher.ui.main.MainActivity

# 4. Fallback driver re-bind only if layout was not yet picked up by InputReader
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

# 5. Verify and launch supervisor.sh
is_matching_proc() {
  local pid="$1"
  local expected="$2"
  [ -n "$pid" ] || return 1
  [ -d "/proc/$pid" ] || return 1
  local cmd
  cmd=$(tr '\000' ' ' < "/proc/$pid/cmdline" 2>/dev/null)
  case "$cmd" in
    *"$expected"*) return 0 ;;
    *) return 1 ;;
  esac
}

SUP_PID=$(cat "$STATE_DIR/supervisor.pid" 2>/dev/null)
if ! is_matching_proc "$SUP_PID" "$BASE/supervisor.sh"; then
  nohup /system/bin/sh "$BASE/supervisor.sh" > "$BASE/supervisor.log" 2>&1 < /dev/null &
fi

# Background service tweaks
(
  pm disable com.dangbei.tvlauncher/com.dangbei.launcher.service.HomeKeyEventCatchService >/dev/null 2>&1
  am start-service -n dev.vodik7.atvtoolsserver/.Service >/dev/null 2>&1
) &
