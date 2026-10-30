#!/system/bin/sh
# debloat.sh
# Freeze bloatware packages on C10H (SK-L1001) using Write-Ahead Logging (WAL).
# Frees ~555MB of RAM and blocks silent remote OTA updates & boot popups.

SCRIPT_DIR=$(cd "$(dirname "$0")" 2>/dev/null && pwd)
STATE_DIR="${STATE_DIR:-/data/local/c10h-debloat}"
SNAPSHOT_FILE="$STATE_DIR/snapshot.txt"
PACKAGES_FILE="${PACKAGES_FILE:-$SCRIPT_DIR/debloat-packages.txt}"

# 1. Snapshot Protection & Transaction State Check
if [ -f "$SNAPSHOT_FILE" ]; then
    if grep -q "^STATUS:COMPLETED" "$SNAPSHOT_FILE"; then
        echo "[!] Active debloat snapshot already exists at: $SNAPSHOT_FILE" >&2
        echo "    Running debloat again would overwrite your original package state record." >&2
        echo "    To restore your system, run: sh restore_bloatware.sh" >&2
        echo "    To force a fresh debloat, remove $SNAPSHOT_FILE first." >&2
        exit 1
    elif grep -q "^STATUS:IN_PROGRESS" "$SNAPSHOT_FILE"; then
        echo "[ERROR] An interrupted debloat transaction was detected at: $SNAPSHOT_FILE" >&2
        echo "        A previous run did not complete cleanly." >&2
        echo "        Please run 'sh restore_bloatware.sh' to recover your original system state." >&2
        exit 1
    else
        echo "[ERROR] Invalid or corrupted snapshot file found at: $SNAPSHOT_FILE" >&2
        echo "        Please check or remove the file before proceeding." >&2
        exit 1
    fi
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
if [ -f "$PACKAGES_FILE" ]; then
    PACKAGES=$(grep -v '^[[:space:]]*#' "$PACKAGES_FILE" | grep -v '^[[:space:]]*$')
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

# 5. Initialize Write-Ahead Log (WAL)
mkdir -p "$STATE_DIR" || { echo "[ERROR] Failed to create state directory $STATE_DIR" >&2; exit 1; }
TIMESTAMP=$(date '+%Y-%m-%d %T')
{
    echo "STATUS:IN_PROGRESS"
    echo "# Debloat WAL transaction started at $TIMESTAMP"
} > "$SNAPSHOT_FILE" || { echo "[ERROR] Failed to write WAL transaction header to $SNAPSHOT_FILE" >&2; exit 1; }
sync || { echo "[ERROR] sync failed during WAL initialization" >&2; exit 1; }

echo "=== Memory Before Debloat ==="
free -m

# 6. Disable packages with write-ahead persistence
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
    # WAL Step: Record intended change to persistent log before changing system state
    if ! echo "PKG:$pkg" >> "$SNAPSHOT_FILE"; then
        echo "[ERROR] WAL write failed for $pkg; aborting debloat to preserve transaction consistency!" >&2
        exit 1
    fi
    if ! sync; then
        echo "[ERROR] sync failed after recording $pkg; aborting debloat!" >&2
        exit 1
    fi

    # Execute disable operation
    if pm disable-user --user 0 "$pkg" >/dev/null 2>&1; then
        am force-stop "$pkg" >/dev/null 2>&1
        DISABLED_COUNT=$((DISABLED_COUNT + 1))
    else
        echo "[ERROR] Failed to disable $pkg via pm disable-user! Retaining WAL entry for recovery." >&2
        echo "        Aborting further debloat operations. Please run restore_bloatware.sh." >&2
        exit 1
    fi
done

# 7. Optimize Dangbei Launcher service hook (record only if currently active)
DANGBEI_SERVICE="com.dangbei.tvlauncher/com.dangbei.launcher.service.HomeKeyEventCatchService"
if pm list packages 2>/dev/null | grep -q "^package:com.dangbei.tvlauncher$"; then
    DUMP_OUT=$(dumpsys package com.dangbei.tvlauncher 2>/dev/null)
    if [ -z "$DUMP_OUT" ] || ! echo "$DUMP_OUT" | grep -q "User 0:"; then
        echo "[!] Warning: Cannot reliably inspect Dangbei launcher state; skipping service modification." >&2
    else
        IS_DISABLED=$(echo "$DUMP_OUT" | awk '
            /User 0:/ { in_u0 = 1; next }
            in_u0 && (/User [0-9]+:/ || /Package Changes:/) { in_u0 = 0; in_dis = 0 }
            in_u0 && /disabledComponents:/ { in_dis = 1; next }
            in_dis {
                if ($0 ~ /:[ \t\r]*$/ || $0 ~ /^[ \t\r]*$/ || $0 ~ /^[^ \t]/) {
                    in_dis = 0
                } else if ($1 != "") {
                    print $1
                }
            }
        ' | grep -x "com.dangbei.launcher.service.HomeKeyEventCatchService")

        if [ -n "$IS_DISABLED" ]; then
            echo "[*] Dangbei HomeKeyEventCatchService is already disabled; skipping snapshot entry."
        else
            if ! echo "SERVICE:$DANGBEI_SERVICE" >> "$SNAPSHOT_FILE"; then
                echo "[ERROR] WAL write failed for $DANGBEI_SERVICE; aborting!" >&2
                exit 1
            fi
            if ! sync; then
                echo "[ERROR] sync failed after recording $DANGBEI_SERVICE; aborting!" >&2
                exit 1
            fi
            if pm disable "$DANGBEI_SERVICE" >/dev/null 2>&1; then
                echo "[+] Disabled Dangbei HomeKeyEventCatchService hook."
            else
                echo "[ERROR] Failed to disable $DANGBEI_SERVICE! Retaining entry for recovery." >&2
                exit 1
            fi
        fi
    fi
fi

# 8. Mark transaction COMPLETED
if ! echo "STATUS:COMPLETED" >> "$SNAPSHOT_FILE"; then
    echo "[ERROR] Failed to commit STATUS:COMPLETED to WAL snapshot!" >&2
    exit 1
fi
if ! sync; then
    echo "[ERROR] sync failed when committing STATUS:COMPLETED!" >&2
    exit 1
fi
sync

echo "=== Memory After Debloat ==="
free -m
echo "[+] Debloat complete. Newly disabled $DISABLED_COUNT packages."
echo "[+] Write-ahead transaction log finalized at $SNAPSHOT_FILE for precise rollback."
