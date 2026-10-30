#!/system/bin/sh
# restore_bloatware.sh
# Precision rollback for C10H (SK-L1001) bloatware freezing.
# Restores ONLY packages and services that were actually frozen by debloat.sh.

STATE_DIR=/data/local/c10h-debloat
SNAPSHOT_FILE="$STATE_DIR/snapshot.txt"
SCRIPT_DIR=$(cd "$(dirname "$0")" 2>/dev/null && pwd)
MODE="${1:-}"

RESTORED_COUNT=0
FAILED_COUNT=0

if [ -f "$SNAPSHOT_FILE" ]; then
    echo "[*] Found debloat state snapshot: $SNAPSHOT_FILE"
    while read -r line || [ -n "$line" ]; do
        case "$line" in
            PKG:*)
                pkg="${line#PKG:}"
                if [ -n "$pkg" ]; then
                    if pm enable "$pkg" >/dev/null 2>&1; then
                        RESTORED_COUNT=$((RESTORED_COUNT + 1))
                    else
                        echo "[!] Warning: failed to re-enable package: $pkg" >&2
                        FAILED_COUNT=$((FAILED_COUNT + 1))
                    fi
                fi
                ;;
            SERVICE:*)
                svc="${line#SERVICE:}"
                if [ -n "$svc" ]; then
                    if pm enable "$svc" >/dev/null 2>&1; then
                        echo "[+] Restored service: $svc"
                    else
                        echo "[!] Warning: failed to re-enable service: $svc" >&2
                        FAILED_COUNT=$((FAILED_COUNT + 1))
                    fi
                fi
                ;;
            *)
                # Comment or blank line
                ;;
        esac
    done < "$SNAPSHOT_FILE"

    if [ "$FAILED_COUNT" -eq 0 ]; then
        # Archive snapshot file only when all operations succeeded
        mv "$SNAPSHOT_FILE" "$SNAPSHOT_FILE.restored"
        echo "[+] Snapshot restore complete. Re-enabled $RESTORED_COUNT packages."
        echo "[+] Archived snapshot to $SNAPSHOT_FILE.restored"
        exit 0
    else
        echo "[ERROR] Restore encountered $FAILED_COUNT failures!" >&2
        echo "        Snapshot retained at $SNAPSHOT_FILE for diagnosis and retry." >&2
        exit 1
    fi
else
    if [ "$MODE" = "--legacy-restore" ]; then
        echo "[*] Running in --legacy-restore mode (unconditional enable from package list)..."
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
            pm enable "$pkg" >/dev/null 2>&1
            RESTORED_COUNT=$((RESTORED_COUNT + 1))
        done

        # Also restore Dangbei service if present
        pm enable com.dangbei.tvlauncher/com.dangbei.launcher.service.HomeKeyEventCatchService >/dev/null 2>&1
        echo "[+] Legacy restore complete. Re-enabled $RESTORED_COUNT packages."
        exit 0
    else
        echo "[ERROR] No active debloat snapshot found at $SNAPSHOT_FILE." >&2
        echo "        Refusing to blindly enable all packages without a record of prior state." >&2
        echo "        If you are restoring an older setup without snapshot support, run:" >&2
        echo "        sh restore_bloatware.sh --legacy-restore" >&2
        exit 1
    fi
fi
