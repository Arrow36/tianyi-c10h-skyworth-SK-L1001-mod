#!/system/bin/sh
# restore_bloatware.sh
# Re-enable all frozen China Telecom / Haobai / Skyworth packages on C10H (SK-L1001)

SCRIPT_DIR=$(cd "$(dirname "$0")" 2>/dev/null && pwd)
if [ -f "$SCRIPT_DIR/debloat-packages.txt" ]; then
    PACKAGES=$(grep -v '^#' "$SCRIPT_DIR/debloat-packages.txt")
else
    PACKAGES="
com.chinatelecom.accloudbox
com.haobai.sipphone
com.skyworthdigital.upgrade
com.skyworthdigital.usbupgrade
com.skyworthdigital.uploadlog
com.tatv.android.TMC
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
done

# To restore the stock Telecom launcher if needed:
# cmd package install-existing --user 0 com.jsdx.speaker.launcher
echo "[+] All frozen packages re-enabled."
