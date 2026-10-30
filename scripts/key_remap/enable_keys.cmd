@echo off
setlocal

set ADB=adb

where %ADB% >nul 2>nul
if errorlevel 1 (
    echo [ERROR] adb command not found in PATH. Please install Android Platform Tools.
    pause
    exit /b 1
)

if "%~1"=="" (
    set TARGET=
    echo [*] No IP specified, using default ADB target device...
) else (
    set TARGET=-s %~1
    echo [*] Connecting to %~1 ...
    %ADB% connect %~1
    if errorlevel 1 (
        echo [ERROR] Failed to connect to %~1.
        pause
        exit /b 1
    )
)

echo [*] Verifying device connection and root permissions...
%ADB% %TARGET% shell id -u | findstr /x 0 >nul 2>&1
if errorlevel 1 goto :fail_root

echo [*] Creating target directory /data/local/codex-screen-toggle/ ...
%ADB% %TARGET% shell "mkdir -p /data/local/codex-screen-toggle"
if errorlevel 1 goto :fail_deploy

echo [*] Pushing scripts and binaries...
for %%F in (
    "toggle.sh"
    "activate.sh"
    "gpio_keypad.idc"
    "codex_gpio_sleep.kl"
    "gpio_event_reader"
    "adc_toggle.sh"
    "adc_keypad.idc"
    "activate_adc.sh"
    "codex_adc_keys.kl"
) do (
    if not exist "%~dp0%%~F" (
        echo [ERROR] Required local file not found: %~dp0%%~F
        goto :fail_deploy
    )
    %ADB% %TARGET% push "%~dp0%%~F" /data/local/codex-screen-toggle/%%~F >nul
    if errorlevel 1 (
        echo [ERROR] Failed to push %%~F to device.
        goto :fail_deploy
    )
)

echo [*] Setting executable permissions...
%ADB% %TARGET% shell "chmod 755 /data/local/codex-screen-toggle/activate.sh /data/local/codex-screen-toggle/activate_adc.sh /data/local/codex-screen-toggle/gpio_event_reader /data/local/codex-screen-toggle/toggle.sh /data/local/codex-screen-toggle/adc_toggle.sh"
if errorlevel 1 goto :fail_deploy

echo [*] Activating key remap daemons...
%ADB% %TARGET% shell "sh /data/local/codex-screen-toggle/activate.sh"
if errorlevel 1 goto :fail_deploy

echo [*] Verifying remote daemon and layout status...
%ADB% %TARGET% shell "ps -ef | grep 'toggle.sh' | grep -v 'grep'" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Verification failed: toggle.sh daemon is not running on device.
    goto :fail_deploy
)

%ADB% %TARGET% shell "dumpsys input" | findstr /c:"codex_gpio_sleep.kl" >nul 2>&1
if errorlevel 1 (
    echo [WARNING] dumpsys input did not report codex_gpio_sleep.kl; verifying layout file...
    %ADB% %TARGET% shell "test -f /data/system/devices/keylayout/codex_gpio_sleep.kl"
    if errorlevel 1 (
        echo [ERROR] Verification failed: Keylayout file missing.
        goto :fail_deploy
    )
)

echo.
echo ========================================================
echo  [OK] Physical key remap enabled and verified.
echo  - Power : Short press = Screen Off/On, Hold 0.35s = Power Menu
echo  - F9    : Short press = Back,          Hold 0.35s = Home
echo  - F10   : Short press = Confirm,       Hold 0.35s = Recents
echo ========================================================
pause
exit /b 0

:fail_root
echo.
echo [ERROR] Root verification failed: ADB is not connected or shell is not running as root (UID is not 0).
echo Please make sure Wireless Root ADB is active on the target device.
pause
exit /b 1

:fail_deploy
echo.
echo [FATAL ERROR] Key remap deployment failed.
echo Please check your ADB connection, device root status, and retry.
pause
exit /b 1
