#!/system/bin/sh
# debloat.sh
# Freeze 36 China Telecom / Haobai / Skyworth OTA / Education bloatware packages on C10H (SK-L1001)
# Frees ~555MB of RAM and blocks silent remote OTA updates & boot popups.

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

echo "=== Memory Before Debloat ==="
free -m

for pkg in $PACKAGES; do
    pm disable-user --user 0 "$pkg" 2>/dev/null
    am force-stop "$pkg" 2>/dev/null
done

echo "=== Memory After Debloat ==="
free -m
