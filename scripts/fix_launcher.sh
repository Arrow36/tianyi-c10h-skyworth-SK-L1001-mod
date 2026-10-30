#!/system/bin/sh
# fix_launcher.sh
# Fixes Android PhoneWindowManager Home key routing on Skyworth C10H (SK-L1001).
#
# Stock /system/build.prop defines:
#   epg.launcher.packagename=com.tatv.android.TMC
# When TMC is debloated or unavailable, PhoneWindowManager.startDockOrHome() throws
# a NullPointerException because pm.getLaunchIntentForPackage("com.tatv.android.TMC")
# returns null, causing Home key dispatch to crash and freeze navigation.
#
# This script points launcher properties to Dangbei Launcher (or stock if Dangbei not found).
# It can be safely executed repeatedly at any time and does NOT depend on key remap daemons.

TARGET_PKG="com.dangbei.tvlauncher"
TARGET_CLS="com.dangbei.launcher.ui.main.MainActivity"

if pm list packages 2>/dev/null | grep -q "^package:${TARGET_PKG}$"; then
    setprop epg.launcher.packagename "$TARGET_PKG"
    setprop sys.deflauncher.pkg "$TARGET_PKG"
    setprop sys.deflauncher.cls "$TARGET_CLS"
    echo "[+] Home launcher property set to $TARGET_PKG ($TARGET_CLS)"
else
    echo "[!] $TARGET_PKG is not installed; leaving system default launcher property unchanged."
fi
