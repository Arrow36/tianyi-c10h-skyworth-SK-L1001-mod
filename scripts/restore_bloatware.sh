#!/system/bin/sh
# restore_bloatware.sh
# Precision rollback for C10H (SK-L1001) bloatware freezing.
# Restores ONLY packages and services that were actually frozen by debloat.sh.

STATE_DIR=/data/local/c10h-debloat
SNAPSHOT_FILE="$STATE_DIR/snapshot.txt"
SCRIPT_DIR=$(cd "$(dirname "$0")" 2>/dev/null && pwd)

RESTORED_COUNT=0

if [ -f "$SNAPSHOT_FILE" ]; then
    echo "[*] Found debloat state snapshot: $SNAPSHOT_FILE"
    while read -r line || [ -n "$line" ]; do
        case "$line" in
            PKG:*)
                pkg="${line#PKG:}"
                if [ -n "$pkg" ]; then
                    pm enable "$pkg" 2>/dev/null
                    RESTORED_COUNT=$((RESTORED_COUNT + 1))
                fi
                ;;
            SERVICE:*)
                svc="${line#SERVICE:}"
                if [ -n "$svc" ]; then
                    pm enable "$svc" 2>/dev/null
                    echo "[+] Restored service: $svc"
                fi
                ;;
            *)
                # Comment or blank line
                ;;
        esac
    done < "$SNAPSHOT_FILE"
    
    # Archive snapshot file so it's not reused
    mv "$SNAPSHOT_FILE" "$SNAPSHOT_FILE.restored"
    echo "[+] Snapshot restore complete. Re-enabled $RESTORED_COUNT packages."
    echo "[+] Archived snapshot to $SNAPSHOT_FILE.restored"
else
    echo "[!] No snapshot file found at $SNAPSHOT_FILE. Performing safe standard restore..."
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

    for pkg in $PACKAGES; do
        pm enable "$pkg" 2>/dev/null
        RESTORED_COUNT=$((RESTORED_COUNT + 1))
    done

    # Also restore Dangbei service if present
    pm enable com.dangbei.tvlauncher/com.dangbei.launcher.service.HomeKeyEventCatchService 2>/dev/null
    echo "[+] Standard restore complete. Re-enabled $RESTORED_COUNT packages."
fi

# To restore the stock Telecom launcher if ever uninstalled:
# cmd package install-existing --user 0 com.jsdx.speaker.launcher
