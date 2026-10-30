#!/system/bin/sh
# debloat.sh
# Freeze bloatware packages on C10H (SK-L1001) with pre-check state snapshots.
# Frees ~555MB of RAM and blocks silent remote OTA updates & boot popups.

SCRIPT_DIR=$(cd "$(dirname "$0")" 2>/dev/null && pwd)
STATE_DIR=/data/local/c10h-debloat
SNAPSHOT_FILE="$STATE_DIR/snapshot.txt"

# 1. First, ensure launcher properties are fixed before freezing anything
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

# 2. Load package list (ignoring comments)
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

# 3. Safety guard for TMC (Stock Launcher)
for pkg in $PACKAGES; do
    if [ "$pkg" = "com.tatv.android.TMC" ]; then
        CUR_LAUNCHER=$(getprop epg.launcher.packagename)
        if [ "$CUR_LAUNCHER" != "com.dangbei.tvlauncher" ]; then
            echo "[!] WARNING: Refusing to disable TMC because epg.launcher.packagename is '$CUR_LAUNCHER'!"
            echo "    Freezing TMC without an active custom launcher will cause Home key crashes."
            echo "    Skipping TMC."
            PACKAGES=$(echo "$PACKAGES" | grep -v '^com.tatv.android.TMC$')
        fi
    fi
done

# 4. Prepare snapshot directory
mkdir -p "$STATE_DIR"
TIMESTAMP=$(date '+%Y-%m-%d %T')
echo "# Debloat snapshot generated at $TIMESTAMP" > "$SNAPSHOT_FILE"

echo "=== Memory Before Debloat ==="
free -m

# 5. Disable packages and record ONLY packages that were actually enabled
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
    # Package is currently enabled; record to snapshot and disable
    echo "PKG:$pkg" >> "$SNAPSHOT_FILE"
    pm disable-user --user 0 "$pkg" 2>/dev/null
    am force-stop "$pkg" 2>/dev/null
    DISABLED_COUNT=$((DISABLED_COUNT + 1))
done

# 6. Optimize Dangbei Launcher service hook
DANGBEI_SERVICE="com.dangbei.tvlauncher/com.dangbei.launcher.service.HomeKeyEventCatchService"
if pm list packages 2>/dev/null | grep -q "package:com.dangbei.tvlauncher"; then
    # Record service disabled state to snapshot
    echo "SERVICE:$DANGBEI_SERVICE" >> "$SNAPSHOT_FILE"
    pm disable "$DANGBEI_SERVICE" 2>/dev/null
fi

echo "=== Memory After Debloat ==="
free -m
echo "[+] Debloat complete. Newly disabled $DISABLED_COUNT packages."
echo "[+] State snapshot saved at $SNAPSHOT_FILE for precise rollback."
