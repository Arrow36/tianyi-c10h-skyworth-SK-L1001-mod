@echo off
setlocal enabledelayedexpansion

set ADB=adb

if "%~1"=="" (
    set TARGET=
    echo [*] No IP specified, using default ADB target device...
) else (
    set TARGET=-s %~1
    echo [*] Connecting to %~1 ...
    %ADB% connect %~1
)

echo [*] Creating target directory /data/local/codex-screen-toggle/ ...
%ADB% %TARGET% shell mkdir -p /data/local/codex-screen-toggle

echo [*] Pushing scripts and binaries...
%ADB% %TARGET% push "%~dp0toggle.sh" /data/local/codex-screen-toggle/toggle.sh
%ADB% %TARGET% push "%~dp0activate.sh" /data/local/codex-screen-toggle/activate.sh
%ADB% %TARGET% push "%~dp0gpio_keypad.idc" /data/local/codex-screen-toggle/gpio_keypad.idc
%ADB% %TARGET% push "%~dp0codex_gpio_sleep.kl" /data/local/codex-screen-toggle/codex_gpio_sleep.kl
%ADB% %TARGET% push "%~dp0gpio_event_reader" /data/local/codex-screen-toggle/gpio_event_reader
%ADB% %TARGET% push "%~dp0adc_toggle.sh" /data/local/codex-screen-toggle/adc_toggle.sh
%ADB% %TARGET% push "%~dp0adc_keypad.idc" /data/local/codex-screen-toggle/adc_keypad.idc
%ADB% %TARGET% push "%~dp0activate_adc.sh" /data/local/codex-screen-toggle/activate_adc.sh
%ADB% %TARGET% push "%~dp0codex_adc_keys.kl" /data/local/codex-screen-toggle/codex_adc_keys.kl

echo [*] Setting executable permissions...
%ADB% %TARGET% shell chmod 755 /data/local/codex-screen-toggle/activate.sh /data/local/codex-screen-toggle/activate_adc.sh /data/local/codex-screen-toggle/gpio_event_reader /data/local/codex-screen-toggle/toggle.sh /data/local/codex-screen-toggle/adc_toggle.sh

echo [*] Activating key remap daemons...
%ADB% %TARGET% shell sh /data/local/codex-screen-toggle/activate.sh

echo [OK] Physical key remap enabled successfully!
pause
