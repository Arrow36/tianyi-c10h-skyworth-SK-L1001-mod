#!/system/bin/sh
# restore_bloatware.sh
# Precision rollback for C10H (SK-L1001) bloatware freezing.
# Restores ONLY packages and services that were actually frozen by debloat.sh.
# Supports recovery from both COMPLETED and interrupted IN_PROGRESS transactions.

STATE_DIR="${STATE_DIR:-/data/local/c10h-debloat}"
SNAPSHOT_FILE="$STATE_DIR/snapshot.txt"
SCRIPT_DIR=$(cd "$(dirname "$0")" 2>/dev/null && pwd)
PACKAGES_FILE="${PACKAGES_FILE:-$SCRIPT_DIR/debloat-packages.txt}"
MODE="${1:-}"

RESTORED_COUNT=0
FAILED_COUNT=0

if [ -f "$SNAPSHOT_FILE" ]; then
    if grep -q "^STATUS:COMPLETED" "$SNAPSHOT_FILE"; then
        echo "[*] Found verified debloat state snapshot: $SNAPSHOT_FILE"
    elif grep -q "^STATUS:IN_PROGRESS" "$SNAPSHOT_FILE"; then
        echo "[!] WARNING: Detected incomplete or interrupted debloat transaction in $SNAPSHOT_FILE."
        echo "[*] Recovering all components recorded up to the interruption point..."
    else
        echo "[ERROR] Snapshot file $SNAPSHOT_FILE is corrupted or missing a valid transaction status header!" >&2
        echo "        Refusing to execute unverified restore. The snapshot will NOT be deleted." >&2
        echo "        Please inspect the snapshot manually or run with --legacy-restore if using legacy format." >&2
        exit 1
    fi

    # Pass 1: Pre-flight static validation of WAL format and record integrity
    PRECHECK_FAILED=0
    while read -r line || [ -n "$line" ]; do
        case "$line" in
            PKG:*)
                pkg="${line#PKG:}"
                if [ -z "$pkg" ] || echo "$pkg" | grep -q '[^a-zA-Z0-9._]'; then
                    echo "[ERROR] Pre-flight validation failed: invalid package identifier '$pkg'" >&2
                    PRECHECK_FAILED=1
                fi
                ;;
            SERVICE:*)
                svc="${line#SERVICE:}"
                if [ -z "$svc" ] || echo "$svc" | grep -q '[^a-zA-Z0-9._/]'; then
                    echo "[ERROR] Pre-flight validation failed: invalid service identifier '$svc'" >&2
                    PRECHECK_FAILED=1
                fi
                ;;
            "STATUS:IN_PROGRESS"|"STATUS:COMPLETED"|"#"*|"")
                # Valid headers, comments, or blank lines
                ;;
            *)
                echo "[ERROR] Pre-flight validation failed: unrecognized record format in WAL: '$line'" >&2
                PRECHECK_FAILED=1
                ;;
        esac
    done < "$SNAPSHOT_FILE"

    if [ "$PRECHECK_FAILED" -ne 0 ]; then
        echo "[ERROR] Snapshot pre-flight validation failed. Refusing to execute restore." >&2
        echo "        Device state has NOT been altered. Snapshot retained at $SNAPSHOT_FILE." >&2
        exit 1
    fi

    # Pass 2: Execute precision restoration (all records pre-verified)
    while read -r line || [ -n "$line" ]; do
        case "$line" in
            PKG:*)
                pkg="${line#PKG:}"
                if [ -n "$pkg" ]; then
                    # Restore component to default state first; fallback to enable
                    if pm default-state --user 0 "$pkg" >/dev/null 2>&1 || pm enable --user 0 "$pkg" >/dev/null 2>&1 || pm enable "$pkg" >/dev/null 2>&1; then
                        RESTORED_COUNT=$((RESTORED_COUNT + 1))
                    else
                        echo "[!] Warning: failed to restore package: $pkg" >&2
                        FAILED_COUNT=$((FAILED_COUNT + 1))
                    fi
                fi
                ;;
            SERVICE:*)
                svc="${line#SERVICE:}"
                if [ -n "$svc" ]; then
                    if pm default-state "$svc" >/dev/null 2>&1 || pm enable "$svc" >/dev/null 2>&1; then
                        echo "[+] Restored service: $svc"
                    else
                        echo "[!] Warning: failed to restore service: $svc" >&2
                        FAILED_COUNT=$((FAILED_COUNT + 1))
                    fi
                fi
                ;;
            "STATUS:"*|"#"*|"")
                # STATUS header, comments, or blank lines
                ;;
        esac
    done < "$SNAPSHOT_FILE"

    if [ "$FAILED_COUNT" -eq 0 ]; then
        # Archive snapshot file only when all operations succeeded
        mv "$SNAPSHOT_FILE" "$SNAPSHOT_FILE.restored" || { echo "[ERROR] Failed to archive snapshot" >&2; exit 1; }
        sync || { echo "[ERROR] sync failed after archiving snapshot" >&2; exit 1; }
        echo "[+] Snapshot restore complete. Restored $RESTORED_COUNT packages."
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

        for pkg in $PACKAGES; do
            pm default-state --user 0 "$pkg" >/dev/null 2>&1 || pm enable --user 0 "$pkg" >/dev/null 2>&1 || pm enable "$pkg" >/dev/null 2>&1
            RESTORED_COUNT=$((RESTORED_COUNT + 1))
        done

        # Also restore Dangbei service if present
        pm default-state "com.dangbei.tvlauncher/com.dangbei.launcher.service.HomeKeyEventCatchService" >/dev/null 2>&1 || pm enable "com.dangbei.tvlauncher/com.dangbei.launcher.service.HomeKeyEventCatchService" >/dev/null 2>&1
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
