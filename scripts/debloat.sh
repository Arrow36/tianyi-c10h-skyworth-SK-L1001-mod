#!/system/bin/sh
# debloat.sh
# Freeze bloatware packages on C10H (SK-L1001) with pre-check state snapshots.
# Frees ~555MB of RAM and blocks silent remote OTA updates & boot popups.

SCRIPT_DIR=$(cd "$(dirname "$0")" 2>/dev/null && pwd)
STATE_DIR=/data/local/c10h-debloat
SNAPSHOT_FILE="$STATE_DIR/snapshot.txt"

# 1. Snapshot Protection: Do not overwrite an existing active snapshot
if [ -f "$SNAPSHOT_FILE" ]; then
    echo "[!] Active debloat snapshot already exists at: $SNAPSHOT_FILE" >&2
    echo "    Running debloat again would overwrite your original package state record." >&2
    echo "    To restore your system, run: sh restore_bloatware.sh" >&2
    echo "    To force a fresh debloat, remove $SNAPSHOT_FILE first." >&2
    exit 1
fi

# 2. First, ensure launcher properties are fixed before freezing anything
if [ -f "$SCRIPT_DIR/fix_launcher.sh" ]; then
    sh "$SCRIPT_DIR/fix_launcher.sh"
else
    TARGET_PKG="com.dangbei.tvlauncher"
    TARGET_CLS="com.dangbei.launcher.ui.main.MainActivity"
    if pm list packages 2>/dev/null | grep -q "^package:${TARGET_PKG}$"; then
        setprop epg.launcher.packagename "$TARGET_PKG"
        setprop sys.deflauncher.pkg "$TARGET_PKG"
        setprop sys.deflauncher.cls "$TARGET_CLS"
    fi
fi

# 3. Load package list (ignoring comments)
if [ -f "$SCRIPT_DIR/debloat-packages.txt" ]; then
    PACKAGES=$(grep -v '^[[:space:]]*#' "$SCRIPT_DIR/debloat-packages.txt" | grep -v '^[[:space:]]*$')
else
    PACKAGES="
com.chinatelecom.accloudbox
com.haobai.sipphone
com.skyworthdigital.upgrade
com.skyworthdigital.usbupgrade
com.skyworthdigital.uploadlog
com.tatv.android.uss
com.telecom.eventtracker
com.ctcc.devops
com.android.ctcc.iotctl
com.skyworth.lnautoconfig
com.skyworth.parentcontrol
cn.dlife.smartcloud.launcher
cn.dlife.smartcloud.album
com.yueme.itv
com.chinatelecom.smartvoicebox
ctc.android.smart.terminal.skill
ctc.dlife.smart.terminal.algorithmserver
com.ctcc.motiondetect
com.dlife.aiassistant
com.jshb.voiceassistant
com.skyworth.skyaiagent
com.vstartek.voice.search
com.yeker.serialservice
com.jshb.midscreen.yxting
com.jshb.midscreen.wsmsg
com.jshb.midscreen.studyapp
com.jshb.midscreen.calendarassistant
com.jshb.midscreen.weatherassistant
com.jshb.health.manager
com.haobai.clock
com.dlife.alarm
com.ihome.android.market
com.bestv.ott.baseservices.zp.jsdx
com.domoko.thumb.yxw
com.mediatek.bledemo
"
fi

# 4. Hard Safety Guard: Never disable com.tatv.android.TMC
# Stock ROM framework in /system/build.prop binds Home key to TMC.
# Freezing TMC without a guaranteed, verified persistent cold-boot override risks breaking Home navigation.
CLEANED_PACKAGES=""
for pkg in $PACKAGES; do
    if [ "$pkg" = "com.tatv.android.TMC" ]; then
        echo "[!] SAFETY GUARD: com.tatv.android.TMC is permanently protected by safety policy."
        echo "    It will NOT be disabled to guarantee Home key navigation reliability across reboots."
    else
        CLEANED_PACKAGES="$CLEANED_PACKAGES $pkg"
    fi
done
PACKAGES="$CLEANED_PACKAGES"

# 5. Prepare snapshot directory
mkdir -p "$STATE_DIR"
TIMESTAMP=$(date '+%Y-%m-%d %T')
TEMP_SNAPSHOT="$STATE_DIR/snapshot.tmp.$$"
echo "# Debloat snapshot generated at $TIMESTAMP" > "$TEMP_SNAPSHOT"

echo "=== Memory Before Debloat ==="
free -m

# 6. Disable packages and record ONLY packages that were actually enabled and successfully disabled
DISABLED_COUNT=0
for pkg in $PACKAGES; do
    # Check if package is installed
    if ! pm path "$pkg" >/dev/null 2>&1; then
        continue
    fi
    # Check if package is already disabled
    if pm list packages -d 2>/dev/null | grep -q "^package:${pkg}$"; then
        continue
    fi
    # Package is currently enabled; disable it and record on verified success
    if pm disable-user --user 0 "$pkg" >/dev/null 2>&1; then
        echo "PKG:$pkg" >> "$TEMP_SNAPSHOT"
        am force-stop "$pkg" >/dev/null 2>&1
        DISABLED_COUNT=$((DISABLED_COUNT + 1))
    else
        echo "[!] Warning: failed to disable $pkg; skipping snapshot record."
    fi
done

# 7. Optimize Dangbei Launcher service hook (record only if currently active)
DANGBEI_SERVICE="com.dangbei.tvlauncher/com.dangbei.launcher.service.HomeKeyEventCatchService"
if pm list packages 2>/dev/null | grep -q "^package:com.dangbei.tvlauncher$"; then
    if dumpsys package com.dangbei.tvlauncher 2>/dev/null | grep -A 10 "disabledComponents:" | grep -q "HomeKeyEventCatchService"; then
        echo "[*] Dangbei HomeKeyEventCatchService is already disabled; skipping snapshot record."
    else
        if pm disable "$DANGBEI_SERVICE" >/dev/null 2>&1; then
            echo "SERVICE:$DANGBEI_SERVICE" >> "$TEMP_SNAPSHOT"
            echo "[+] Disabled Dangbei HomeKeyEventCatchService hook."
        fi
    fi
fi

# 8. Atomically commit the snapshot file
mv "$TEMP_SNAPSHOT" "$SNAPSHOT_FILE"

echo "=== Memory After Debloat ==="
free -m
echo "[+] Debloat complete. Newly disabled $DISABLED_COUNT packages."
echo "[+] State snapshot saved at $SNAPSHOT_FILE for precise rollback."
