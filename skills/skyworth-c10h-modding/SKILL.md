---
name: skyworth-c10h-modding
description: Complete guide and automation workflows for unlocking, enabling persistent Wireless Root ADB, replacing the stock launcher, debloating, fixing 32-bit Android 9 native library collisions, and extracting runtime WebView IPTV streams on the China Telecom Skyworth C10H (SK-L1001 / p291_iptv) smart screen.
---

# Skyworth C10H (SK-L1001) Unlocking & Modding Skill

Use this skill when assisting a user with a **China Telecom Tianyi Smart Screen C10H (天翼智屏 C10H / 创维 SK-L1001, `p291_iptv`, Amlogic S905L3A-P, Android 9 32-bit `armeabi-v7a`)**.

## 1. Device Architecture & Quirks

- **SoC / ABI**: Amlogic S905L3A-P (`ro.board=AmlogicS905L3AP`), running 32-bit Android 9 (`armeabi-v7a,armeabi`). Pure 64-bit (`arm64-v8a`) APKs will fail with `INSTALL_FAILED_NO_MATCHING_ABIS`.
- **Build Type**: `userdebug`, `test-keys`, `androidboot.selinux=disabled`.
- **Stock Launcher Hijack**: `PhoneWindowManager.getLauncherIntent()` in `/system/framework/services.jar` and `/system/app/LNAutoconfig/LNAutoconfig.apk` hardcode `com.jsdx.speaker.launcher` when `Settings.System.spkmode == "1"`.
- **3-Minute ADB Timeout Trap**: `PhoneWindowManager$15` registers a `ContentObserver` on `Settings.Global.adb_enabled` and checks `/data/local/adbauth.txt` via `com.skyworth.sys.adb.AdbUtils.readAuthTimeFromFile()`. Setting `settings put global adb_enabled 1` triggers a 180-second timer that shuts down `adbd`.
  - **Fix**: Never run `settings put global adb_enabled 1`. Start `adbd` purely via system properties (`setprop service.adb.root 1; setprop service.adb.tcp.port 5555; setprop ctc.sky.adbd_debug true; setprop ctl.start adbd`).

## 2. Step-by-Step Unlocking Workflow

### Phase 1: Initial Third-Party Launcher Installation (No ADB)
1. Share PC internet to USB Ethernet adapter (`192.168.137.1`) and connect Ethernet to C10H.
2. Open the stock App Store on C10H and download NetEase Cloud Music (`http://appmarket.zhongping.jsinfo.net:6060/appserver/uploads/10778457142562508.apk`).
3. Serve `dbzm_4.1.7_dangbei.apk` (`com.dangbei.tvlauncher`) on `http://192.168.137.1:6061/appserver/uploads/10778457142562508.apk`.
4. Use `WinDivert` to rewrite the HTTP `302` response `Location` header from the app store server to `http://192.168.137.1:6061/...` (maintaining packet length and recalculating TCP/IP checksums).

### Phase 2: Extracting System APKs & Unlocking Root Wireless ADB via `FactoryTestTool`
1. Install **ES File Explorer** (`com.estrongs.android.pop`) and **Activity Launcher** (`de.szalkowski.activitylauncher`).
2. Use ES File Explorer's App Manager to back up `/system/app/YKFactory/YKFactory.apk` (`com.yeker.factorytest.tool`, runs as `android.uid.system`), and turn on ES File Explorer's FTP server ("远程管理") so the PC/AI can pull and analyze the APK over Wi-Fi.
3. `FactoryTestTool` reads `/sdcard/factoryTest/factorytest_config.xml`, encrypted with repeating-key XOR key **`"yekerv587"`**.
4. In `TestLocationActivity.initData()`, `FactoryTestTool` synchronously executes the `<SystemOrder><setOrderPoint>` tag via `ShellUtils.execCmd(..., false)` as `uid=1000(system)`.
5. Set `<setOrderPoint>` in `configs/factorytest_config_plain.xml` to:
   ```xml
   <setOrderPoint>setprop service.adb.root 1; setprop service.adb.tcp.port 5555; setprop persist.adb.tcp.port 5555; setprop ctc.sky.adbd_debug true; setprop persist.sys.usb.config mtp,adb; setprop sys.usb.config mtp,adb; setprop ctl.restart adbd; setprop ctl.start adbd; setprop sys.sky.ctcc.shell_1 "/system/bin/sh /data/local/codex-screen-toggle/activate.sh"; setprop ctl.start telecom_shell; am start -n com.dangbei.tvlauncher/com.dangbei.launcher.ui.main.MainActivity; am force-stop com.yeker.factorytest.tool</setOrderPoint>
   ```
6. Encrypt with `python scripts/factorytest_crypt.py configs/factorytest_config_plain.xml configs/factorytest_config.xml` and upload to `/sdcard/factoryTest/factorytest_config.xml` via ES FTP (first time) or `adb push`.
7. Lock the config file against deletion (`AppBroadcastReceiver` attempts to delete `/sdcard/factoryTest` on `BOOT_COMPLETED` when `SkyFactoryGetVerify()` returns `"pass"`):
   ```sh
   adb shell "toybox chattr +i /data/media/0/factoryTest/factorytest_config.xml; pm disable com.yeker.factorytest.tool/com.yeker.factorytest.tool.broadcastReceiver.AppBroadcastReceiver"
   ```

### Phase 3: Auto-Start Wireless Root ADB on Boot
1. Install `configs/AutoStartHelper.apk` (`com.autostart.factoryhelper`, built via `scripts/build_autostart_apk.py`), which listens to `BOOT_COMPLETED`, sleeps 5 seconds (so Dangbei Launcher finishes resuming first and does not pre-empt `StartupActivity`), and launches `com.yeker.factorytest.tool/.activity.StartupActivity`.
2. Un-stop and whitelist `com.autostart.factoryhelper`:
   ```sh
   adb install -r configs/AutoStartHelper.apk
   adb shell "cmd deviceidle whitelist +com.autostart.factoryhelper; appops set com.autostart.factoryhelper RUN_IN_BACKGROUND allow; appops set com.autostart.factoryhelper RUN_ANY_IN_BACKGROUND allow; appops set com.autostart.factoryhelper SYSTEM_ALERT_WINDOW allow; am broadcast -a android.intent.action.BOOT_COMPLETED -n com.autostart.factoryhelper/.BootReceiver --include-stopped-packages"
   ```

### Phase 4: Default Launcher Fix & System Debloat
1. Remove the stock launcher for user 0 so Dangbei Launcher handles boot and HOME key presses:
   ```sh
   adb shell "pm uninstall -k --user 0 com.jsdx.speaker.launcher"
   ```
2. Run `scripts/debloat.sh` over ADB to freeze 36 Telecom/Haobai/OTA/Education bloatware packages (including the 90-second boot popup `com.chinatelecom.accloudbox` and `com.haobai.sipphone`), freeing ~555MB RAM, and disables `com.dangbei.tvlauncher/com.dangbei.launcher.service.HomeKeyEventCatchService` to prevent desktop reload and wallpaper lag on system dialog close.

### Phase 5: Fixing 32-Bit Android 9 `libcrypto.so` / `libssl.so` Symbol Collisions
- Apps like modern Bilibili (`tv.danmaku.bili`) bundle their own BoringSSL `libcrypto.so` and `libssl.so` (referencing symbols like `EVP_hpke_aes_128_gcm`). Because Android 9 Zygote preloads `/system/lib/libcrypto.so` and `/system/lib/libssl.so`, dynamic linking resolves `DT_NEEDED: libcrypto.so` to the older system library and crashes with `UnsatisfiedLinkError`.
- Use `scripts/prepare_bilibili_ssl.py` on host to binary-patch `libcrypto.so` -> `libbili_o.so` (12 bytes) and `libssl.so` -> `libbsl.so` (9 bytes) in ELF `PT_DYNAMIC` / `DT_STRTAB`, then apply via `scripts/fix_bilibili_ssl.sh apply` with transactional WAL and automatic rollback protection inside `/data/app/tv.danmaku.bili-*/lib/arm/`.

### Phase 6: High-Performance Physical Key Remapping & Kernel uinput Daemon
1. Push `scripts/key_remap/*` to `/data/local/codex-screen-toggle/` on the device and set executable permissions (`chmod 755`).
2. Architecture & Latency Optimization:
   - **Kernel-level `/dev/uinput` Injection (`uinput_injector`)**: 5.4KB zero-libc ARM binary registers `c10h_keys` virtual hardware device and listens on `$STATE_DIR/key.fifo`. Emits native Linux `input_event` in `<0.05ms`, dropping short-press latency from **~1000ms down to 13ms~21ms (50x speedup)** by bypassing JVM cold starts.
   - **Zero Flash I/O Hot Path**: Replaced eMMC state files (`touch`/`rm` 53ms) with in-memory PID signals and `/dev` tmpfs flags.
   - **Watchdog Supervisor (`supervisor.sh`)**: Background monitor for `uinput_injector`, `toggle.sh`, and `adc_toggle.sh` with stepped backoff throttling and in-place log rotation.
   - **POSIX Atomic Locks**: Uses `ln "$tmp" "$lock"` with owner PID verification and atomic reclaim to prevent duplicate listeners.
   - **Process Decoupling**: Activated via `setprop sys.sky.ctcc.shell_1 ...; setprop ctl.start telecom_shell` to run under `init` (PPID 1) rather than FactoryTestTool cgroup.
3. The solution remaps:
   - **Power** (scancode 116): short press (<0.35s) -> display sleep/wake via `KEY_SLEEP`/`KEY_WAKEUP` (~15ms), long press (>=0.35s) -> native shutdown/reboot dialog via `REQUEST_SHUTDOWN` activity (~70ms).
   - **F9** (scancode 67): short press (<0.35s) -> Back via `uinput` (`KEY_BACK` ~15ms), long press (>=0.35s) -> Home via `am start Home` (90ms).
   - **F10** (scancode 68): short press (<0.35s) -> Confirm via `uinput` (`KEY_ENTER` ~15ms), long press (>=0.35s) -> Recents via `am start RecentsActivity` (120ms).
   - Triggering model: Instant non-blocking trigger when held >=0.35s (no need to wait for finger release).
4. Uses driver unbind/bind reload trick to apply custom layouts in `/data/system/devices/keylayout/` without modifying read-only `/vendor`.
5. Executes automatically on boot via FactoryTestTool `<setOrderPoint>` calling `telecom_shell`.
