# skyworth-c10h-hack

> **天翼智屏 C10H (创维 SK-L1001 / p291_iptv) 免拆机破局、持久化无线 Root ADB 解锁、系统官改精简与运行时 IPTV 直播源提取指南**

本项目完整记录并开源了中国电信定制智能音箱屏 **天翼智屏 C10H (创维 SK-L1001)** 的完整软破解、免拆机解锁、持久化无线 Root ADB 保活、系统级防撤回/防 OTA 精简、32位动态库符号冲突热补丁，以及基于 WebView 调试接口无损提取官方授权 IPTV 直播流的全套技术方案。

> **免责声明**：本项目所有技术记录与自动化脚本仅供嵌入式 Android 系统安全研究、设备二次利用与技术学习交流使用。项目中涉及的直播流抓取基于合法授权设备的运行时调试，不包含任何绕过认证或逆向破解鉴权算法的代码。请勿用于商业目的或非法传播。

---

## 目录

- [一、设备全貌与硬件规格](#一设备全貌与硬件规格)
- [二、初始封锁与防护机制](#二初始封锁与防护机制)
- [三、免 ADB 破局：网络流量劫持替换当贝桌面](#三免-adb-破局网络流量劫持替换当贝桌面)
- [四、逆向工厂模式：解密与命令注入开启无线 Root ADB](#四逆向工厂模式解密与命令注入开启无线-root-adb)
- [五、接管桌面与消除开机弹窗](#五接管桌面与消除开机弹窗)
- [六、构建无线 Root ADB 开机持久化闭环](#六构建无线-root-adb-开机持久化闭环)
- [七、系统瘦身与防升级：一键冻结 36 个毒瘤组件](#七系统瘦身与防升级一键冻结-36-个毒瘤组件)
- [八、32位 Android 9 动态库符号污染与 B 站闪退热修复](#八32位-android-9-动态库符号污染与-b-站闪退热修复)
- [九、实战进阶：运行时 WebView 调试提取 72 个 IPTV 频道直播源](#九实战进阶运行时-webview-调试提取-72-个-iptv-频道直播源)
- [十、日常使用技巧、遥控方案与已知遗留问题](#十日常使用技巧遥控方案与已知遗留问题)
- [十一、仓库结构与使用方法](#十一仓库结构与使用方法)

---

## 一、设备全貌与硬件规格

天翼智屏 C10H 是中国电信推出的一款 10.1 英寸带屏智能音箱，由创维数字（Skyworth Digital）代工，硬件型号为 `SK-L1001`，内部主板平台代号 `p291_iptv`。

| 硬件项 | 参数规格 / 系统信息 | 备注说明 |
| :--- | :--- | :--- |
| **SoC** | 晶晨 **Amlogic S905L3A-P** (4x ARM Cortex-A55 @ 1.9GHz) | 性能足以流畅硬解 4K H.265 / 1080P 视频 |
| **系统架构** | **32 位 ARMv7** (`armeabi-v7a`, `armeabi`) | 内核 4.9.113，不支持纯 64 位 APK |
| **内存与存储** | **2GB RAM + 64GB eMMC 5.0** | `/data` 分区总容量高达 **51GB**（剩余 ~48GB） |
| **屏幕** | 10.1 英寸 1280×800 IPS 液晶屏 (`panel_type=lcd_8`) | 横向使用，密闭集成 Jadard JD9366TC 触控屏 |
| **音频外设** | 独立大音腔双立体声喇叭 + 聆思 CSK6012 阵列麦克风 | 音质饱满，适合作为桌面独立音乐屏 |
| **系统版本** | **Android 9** (`ro.build.version.release=9`) | `buildvariant=userdebug`, `selinux=disabled` |

---

## 二、初始封锁与防护机制

原厂固件具有极强的运营商定制色彩与锁闭逻辑：

1. **桌面劫持与安装限制**：开机硬编码拉起电信定制桌面 `com.jsdx.speaker.launcher`，系统自带应用中心仅提供少量定制应用，禁止通过常规浏览器或文件管理器自由安装第三方 APK。
2. **隐藏开发者选项与 ADB**：系统设置中移除了开发者选项入口，即便连击版本号也无法开启标准 USB 调试或无线调试。
3. **隐藏后门与“环境切换”彩蛋**：在原厂设置中连续点击 MAC 地址，会弹出隐藏的“选择使用的环境”界面，界面结构如下：
   - 选项列表：`[○] 开发环境` / `[○] 测试环境` / `[○] 生产环境`
   - 功能按钮：`[确认环境]`、`[清除缓存]`、`[退出]`
   经逆向与抓包验证，该功能仅用于切换电信端云业务与日志的上报服务器地址，在未获取底层 shell 时无法直接激活系统级 ADB。
4. **开机 90 秒强占弹窗**：每次冷启动开机，系统都会弹出 `com.chinatelecom.accloudbox`（一点登录授权）界面，必须手动点击右上角关闭才能看到内容。
5. **3 分钟 ADB 倒计时自杀陷阱**：在系统框架 `PhoneWindowManager` 中埋设了定时器，一旦监测到 `Settings.Global.adb_enabled == 1`，将触发 180 秒倒计时，随后强制杀死 `adbd` 守护进程。

---

## 三、免 ADB 破局：网络流量劫持替换当贝桌面

在没有任何 ADB 权限和文件安装入口的情况下，我们利用了系统预装应用中心的**未加密 HTTP 通信漏洞**实现了零权限突破。

### 1. 抓包分析

通过 Windows 电脑开启热点/网络共享直连智屏（电脑端 IP：`192.168.137.1`，智屏由电脑分配内网 IP），在智屏的应用中心中触发下载“网易云音乐”。通过抓包发现：
- 设备先向应用商店服务器发送 HTTP GET：
  ```http
  GET /appserver/uploads/10778457142562508.apk HTTP/1.1
  Host: appmarket.zhongping.jsinfo.net:6060
  ```
- 商店服务器返回 HTTP `302 Moved Temporarily`，`Location` 头重定向至 CDN 下载地址。

### 2. WinDivert 精准改写 `302 Location`

由于早期尝试“给网卡绑定下载服 IP”和“回环地址截流”均因 NAT 转发或端口路由失败，最终采取了基于 WinDivert 底层驱动的 TCP 重写方案：
1. 电脑本地 `192.168.137.1:6061` 挂载当贝桌面 APK（`dbzm_4.1.7_dangbei.apk`，重命名保持与目标一致）。
2. 使用 WinDivert 过滤发往设备的 `302` 数据包，将其 `Location` 替换为电脑本地 HTTP 服务的下载地址，保持数据包字节长度填充不变并重新计算 IP/TCP Checksum。
3. 在设备端卸载网易云并重新点击“安装”，设备跟随被篡改的 302 地址拉取了当贝桌面。系统应用中心利用内部签名权限（`android.permission.INSTALL_PACKAGES`）顺利将当贝桌面安装进系统！

---

## 四、逆向工厂模式：解密与命令注入开启无线 Root ADB

进入当贝桌面后，虽然有了可视化启动器，但由于系统依然缺乏 Root 权限且开机会重置，必须拿到持久化 Shell。

### 1. 备份与逆向工厂测试工具

通过当贝市场装入 **ES 文件浏览器**（`com.estrongs.android.pop`）和 **Activity Launcher**。
- 打开 ES 文件浏览器的“应用备份”功能，将预装的系统应用 `/system/app/YKFactory/YKFactory.apk`（包名 `com.yeker.factorytest.tool`）导出。
- 启动 ES 文件浏览器的“远程管理器”（内置 FTP 服务），电脑端直接从智屏拉取导出的 APK 进行逆向分析。

### 2. 发现命令注入与异或加密

逆向分析 `YKFactory.odex`（classes.dex）发现：
- 该应用声明了 `android:sharedUserId="android.uid.system"`，拥有极高系统权限。
- 应用启动时会尝试读取 `/sdcard/factoryTest/factorytest_config.xml`。
- 读取逻辑采用单字节循环异或（XOR）加密，加密密钥硬编码为：
  ```python
  XOR_KEY = b"yekerv587"
  ```
- 在 `com.yeker.factorytest.tool.activity.TestLocationActivity` 的 `initData()` 方法中，存在直接执行 Shell 命令的同步调用：
  ```java
  // 读取 XML 中的 <SystemOrder><setOrderPoint> 节点内容并直接通过 ShellUtils 执行
  ShellUtils.execCmd(systemOrderBean.getSetOrderPoint(), false);
  ```

### 3. 解锁无线 Root ADB

利用 `scripts/factorytest_crypt.py` 工具，我们构造了注入命令并重新加密打包：
```xml
<setOrderPoint>setprop service.adb.root 1; setprop service.adb.tcp.port 5555; setprop persist.adb.tcp.port 5555; setprop ctc.sky.adbd_debug true; setprop persist.sys.usb.config mtp,adb; setprop sys.usb.config mtp,adb; setprop ctl.restart adbd; setprop ctl.start adbd; am start -n com.dangbei.tvlauncher/com.dangbei.launcher.ui.main.MainActivity; am force-stop com.yeker.factorytest.tool</setOrderPoint>
```
将加密后的 `factorytest_config.xml` 放回 `/sdcard/factoryTest/` 目录，在 Activity Launcher 中点开 `FactoryTestTool`，系统瞬间启动了 `adbd`（端口 5555），并自动执行返回当贝桌面与自我关闭。电脑端执行：
```sh
adb connect 192.168.5.18:5555
adb -s 192.168.5.18:5555 root
```
成功取得 `uid=0(root)` 权限！

---

## 五、接管桌面与消除开机弹窗

### 1. 解决 HOME 键与开机强制回退电信桌面

逆向 `/system/framework/services.jar` 中的 `PhoneWindowManager.getLauncherIntent()` 发现，当系统属性 `spkmode == "1"` 时，系统在接收到 HOME 键或启动事件时，会无视用户的默认桌面选择，强制拉起 `com.jsdx.speaker.launcher`。

在 Root 权限下，通过彻底卸载当前用户的原厂桌面解决：
```sh
adb shell "pm uninstall -k --user 0 com.jsdx.speaker.launcher"
```
卸载后，系统自动将唯一的 `com.dangbei.tvlauncher` 升级为主桌面，HOME 键恢复正常。

### 2. 彻底禁用开机 90 秒弹窗

通过抓取冷启动 `logcat`，确认弹窗属于以下两个电信独立包：
```sh
adb shell "pm disable-user --user 0 com.chinatelecom.accloudbox"  # 一点登录授权
adb shell "pm disable-user --user 0 com.haobai.sipphone"         # 号百固话VPN弹窗
```
执行后冷启动不再有任何遮挡。

---

## 六、构建无线 Root ADB 开机持久化闭环

在实现了无线 ADB 后，面临两个严峻问题：
1. **开机 3 分钟后 ADB 自动断开**：
   `logcat` 抛出 `AdbUtils.readAuthTimeFromFile(/data/local/adbauth.txt)` 找不到授权文件的异常。经分析，只要触发了 `settings put global adb_enabled 1`，创维的监视线程就会启动 180 秒倒计时并停用 `adbd`。
   **解决策略**：在启动脚本中坚决不碰 `adb_enabled` 数据库项，仅通过底层属性 `setprop service.adb.tcp.port 5555` 与 `setprop ctl.start adbd` 拉起守护进程，规避倒计时。
2. **FactoryTestTool 开机自删配置**：
   `FactoryTestTool` 的 `AppBroadcastReceiver` 在接收到系统 `BOOT_COMPLETED` 时，会调用 JNI 获取设备校验状态。由于返回值为 `"pass"`，它会自动执行删除 `/sdcard/factoryTest/` 文件夹的代码。
   **解决策略**：使用 Linux 文件扩展属性加锁：
   ```sh
   adb shell "toybox chattr +i /data/media/0/factoryTest/factorytest_config.xml"
   adb shell "pm disable com.yeker.factorytest.tool/com.yeker.factorytest.tool.broadcastReceiver.AppBroadcastReceiver"
   ```
3. **开机静默自动触发守护（AutoStartHelper.apk）**：
   为了让机器每次开机都不需要手动点击图标，我们编写了纯 Python 工具 `scripts/build_autostart_apk.py`，无需 Android SDK 即可自动生成带 V1 签名的轻量自启应用 `AutoStartHelper.apk`（仅 ~2KB）。
   - 该助手监听系统 `BOOT_COMPLETED` 广播；
   - 内部增加了 **5 秒延时**（避免系统刚开机时当贝桌面初始化抢焦点导致工厂工具被切至后台）；
   - 延时后静默拉起 `FactoryTestTool`，触发其执行命令开启 Root ADB 并立即自我终止（`force-stop`），全过程屏幕仅闪烁约 1 秒，无缝返回当贝桌面。

---

## 七、系统瘦身与防升级：一键冻结 36 个毒瘤组件

智屏原生搭载 2GB 内存，但由于电信预装了大量推送、语音唤醒、家长监控、OTA 检测进程，冷开机内存占用高达 **1.88GB**，可用仅剩 **125MB**。

运行项目提供的 `scripts/debloat.sh`：
```sh
adb push scripts/debloat.sh /data/local/tmp/
adb shell "sh /data/local/tmp/debloat.sh"
```
**优化效果**：
- 禁用了包括 `com.skyworthdigital.upgrade`、`com.tatv.android.TMC`、`com.ctcc.devops` 在内的所有远程静默升级服务，彻底杜绝固件被运营商远程覆盖锁死的隐患；
- 冻结了翼家智话、小翼管家、各种冗余语音助手与学习推送组件；
- **可用内存从 125MB 提升至 680MB 以上**（可用内存提升 **5.4 倍**），整机操作脱胎换骨。

---

## 八、32位 Android 9 动态库符号污染与 B 站闪退热修复

### 1. 故障复现

安装官方新版哔哩哔哩（`tv.danmaku.bili`）后，应用启动必定秒崩。崩溃日志如下：
```text
E System  : ##loadLibrary0## /data/app/tv.danmaku.bili-.../lib/arm/libignet.so error: 
            dlopen failed: cannot locate symbol "EVP_hpke_aes_128_gcm" referenced by ".../libssl.so"
I tv.danmaku.bil: Rejecting re-init on previously-failed class: java.lang.UnsatisfiedLinkError: Library ignet not found
```

### 2. 根本原因

Android 9 的 `Zygote` 进程在系统初始化阶段，预先在全局命名空间中加载了老旧的 `/system/lib/libcrypto.so` 和 `/system/lib/libssl.so`。新版 B 站自身虽然携带了支持现代加密算法（包含 HPKE 接口）的私有 BoringSSL 动态库，但因文件名完全同名，Linux 动态链接器（linker）优先匹配到了系统全局的旧库，导致符号缺失崩溃。

### 3. 热补丁方案

我们无需重编译 APK，直接对设备中的 ELF 二进制文件执行原位字符替换（保持字符串长度完全相等以避免破坏 ELF 节头偏移）：
- `libcrypto.so` (12 字符) $\rightarrow$ `libbili_o.so` (12 字符)
- `libssl.so` (9 字符) $\rightarrow$ `libbsl.so` (9 字符)

直接执行提供的修复脚本：
```sh
adb push scripts/fix_bilibili_ssl.sh /data/local/tmp/
adb shell "sh /data/local/tmp/fix_bilibili_ssl.sh"
```
修改后，B 站动态库精准绑定私有副本，新版客户端完美运行，视频播放与弹幕一切正常！

---

## 九、实战进阶：运行时 WebView 调试提取 72 个 IPTV 频道直播源

在许多 IPTV 播放盒或带屏音箱中，直播流地址通常不写死在安装包中，而是依赖前端页面鉴权动态发放。

### 1. 发现 WebView 调试入口

通过查看系统直播页面启动日志，发现其内嵌的浏览器容器打开了 Android WebView 远程调试端口（DevTools Socket）。

### 2. 端口转发与数据读取

利用已固化的无线 ADB，在电脑端转发调试 Unix Domain Socket：
```sh
adb forward tcp:9222 localabstract:webview_devtools_remote_<PID>
```
在电脑端 Chrome/Edge 打开 `chrome://inspect` 或通过 CDP 协议通信，直接读取运行时 DOM 树和 JavaScript 上下文，一次性获取到当前设备被授权的 **完整 72 个直播频道名称与频点编号**。

### 3. 提取鉴权播放地址与 TS 流本地转接

前端页面在用户切换频道时，会将鉴权后的 `PlayURL`（带有时效性 Token 和会话参数）缓存在 Session 中。我们在页面运行态直接导出该数据集合，并自动格式化生成标准的 `.m3u` 与 `.txt` 播放列表。为了让电脑端播放器（如 PotPlayer）能稳定解码部分特殊的组播/单播封装，配合轻量级本地 Python 脚本实现了 TS 流的转接代理。

---

## 十、日常使用技巧、遥控方案与已知遗留问题

### 1. 无配套遥控器的触控与远程控制方案
- **日常使用**：本机为 10.1 寸电容触控屏，绝大部分平板/电视版软件可直接在屏幕上触控点击。
- **手机无线遥控**：在手机上安装 **ATV Tools** 或支持 Android TV 协议的 ADB 遥控器应用，通过连接设备的 IP（`192.168.x.x:5555`）实现方向键、确认键、音量调节与返回操作，完全无需购买物理遥控器。

### 2. 机身实体按键多功能扩展与长短按重映射（免改 vendor + 开机自启）
本机正面/顶部自带 3 个实体按键。原厂固件下按键功能单一且受限。我们通过“**动态重载 KeyLayout + 极简原生事件监听器 + FactoryTestTool 自启注入**”的组合方案，完全在用户空间（`/data`）实现了多功能按键映射：

| 实体按键 | 对应驱动设备 | 扫描码 (Scancode) | 重映射行为 | 判定阈值 |
|---|---|---|---|---|
| **电源键** | `gpio_keypad` | 116 (`KEY_POWER`) | **短按：息屏 / 亮屏切换**（检测 `sys.switch.screen` 执行 223/224）<br>**长按：呼出原生系统关机与重启菜单** | 松开判定：<0.6s 为开关屏，≥0.6s 呼出关机/重启面板 |
| **F9 键** | `gpio_keypad` | 67 | **短按：返回 (BACK / `keyevent 4`)**<br>**长按：主页 (HOME / `keyevent 3`)** | 松开判定：<0.6s 为返回，≥0.6s 为主页（长按不会误触发返回） |
| **F10 键** | `adc_keypad` | 68 (原静音) | **短按：确认 (CONFIRM / `keyevent 23`)**<br>**长按：最近任务卡片 (`RecentsActivity`)** | 松开判定：<0.6s 为确认，≥0.6s 呼出后台多任务卡片 |

#### 关键技术亮点
1. **免写只读 `/vendor` 分区的动态 Layout 注入**：
   设备的 `/vendor` 分区存在只读硬保护（`mount -o remount,rw /vendor` 会直接被内核拒绝）。我们利用 Android InputManager 的搜索路径机制，将定制的 `.kl` 和 `.idc` 写入 `/data/system/devices/keylayout/`，然后通过驱动总线热插拔指令：
   ```sh
   echo gpio_keypad > /sys/bus/platform/drivers/gpio-keypad/unbind
   echo gpio_keypad > /sys/bus/platform/drivers/gpio-keypad/bind
   echo adc_keypad > /sys/bus/platform/drivers/adc_keypad/unbind
   echo adc_keypad > /sys/bus/platform/drivers/adc_keypad/bind
   ```
   使内核重新加载输入设备，即刻使自定义 KeyLayout 生效。
2. **456 字节的微型原生监听器 (`gpio_event_reader`)**：
   为了保证绝对的响应速度与极低内存占用（不足 0.1MB），使用纯 ARM 汇编编写了 Linux `input_event` 解析器（源码见 `scripts/key_remap/gpio_event_reader.S`），精确捕获微秒级按下/松开时间差，长按不会触发短按的伪事件。
3. **断电重启无感保活**：
   在 FactoryTestTool 的自启节点 `<setOrderPoint>` 中植入了 `(sh /data/local/codex-screen-toggle/activate.sh) &`，开机由系统 root 权限服务自动拉起两套按键守护，机器即使拔电冷重启也能全自动维持映射。
4. **根治“返回桌面与多任务卡顿 1~2 秒”的双重元凶（重大突破）**：
   - **元凶一（底层系统级崩溃）**：经反编译 `/system/framework/oat/arm/services.odex`（`PhoneWindowManager.startDockOrHome` 偏移 0x0038~0x0041）发现，原厂 ROM 在 `/system/build.prop` 中写死了默认启动器 `epg.launcher.packagename=com.tatv.android.TMC`。在精简瘦身冻结 TMC 后，系统每次收到 Home 键都会在 `intent.putExtra("GoHome", "true")` 处抛出未捕获的 `NullPointerException` 异常！导致按键分发在 Native JNI 层直接崩溃中断，被迫等待 1~2 秒超时才由系统兜底拉起。
   - **元凶二（当贝桌面的“自杀式重启”服务）**：从多任务卡片（Recents）返回桌面时，系统会向全局广播 `CLOSE_SYSTEM_DIALOGS`。反编译当贝桌面 APK（`classes2.dex`）发现，其内置的 `com.dangbei.launcher.service.HomeKeyEventCatchService` 捕获到该广播后，会强行调用 `launchApp("重启")` 并触发 `LruBitmapPool.clearMemory()`，**主动销毁桌面上全部已渲染好的图标位图缓存**，强行重新走一遍冷启动网络加载！在这 1~2 秒重载期间，桌面图标全无，导致整个屏幕“裸奔”只剩背景壁纸。
   - **完美根治方案**：
     1. 在启动与按键脚本中注入属性纠偏：`setprop epg.launcher.packagename com.dangbei.tvlauncher`，彻底消除 Framework 空指针崩溃。
     2. 深度冻结当贝的自毁重载服务：`pm disable com.dangbei.tvlauncher/com.dangbei.launcher.service.HomeKeyEventCatchService`，使当贝桌面回归为标准原生的 Android Home 栈唤醒，图标缓存毫发无损保留。
     3. 修正按键调度意图为 `am start -a android.intent.action.MAIN -c android.intent.category.HOME`，确保桌面永远运行在系统的 `Stack #0` 原生 Home 栈中。
     4. 实测从多任务切回桌面与 Home 返回的耗时从原本的 1500ms~2500ms **断崖式下降至 0.09s ~ 0.22s**，彻底告别卡壁纸假象，桌面秒切极度丝滑！

### 3. 应用安装架构避坑（重要）
- 本机硬件为 32 位（`armeabi-v7a`），安装大型应用时**请务必选择 32 位版或全架构通用版（Universal）**。
- 试图安装纯 64 位包（例如最新版酷安等只有 `arm64-v8a` 的 APK）会直接触发 `INSTALL_FAILED_NO_MATCHING_ABIS` 错误。

### 4. 当前已知体验瑕疵（待后续攻克）
1. **原生 Android 设置未完全独立暴露**：原厂设置被深度裁切，部分高级原生系统设置目前需要通过 Activity Launcher 显式调用内部 Intent（例如 `com.android.settings/.Settings`）才能进入。（此前“返回桌面卡顿 1~2 秒”的问题已在按键映射章节中通过属性重定向彻底解决）。

---

## 十一、仓库结构与使用方法

```text
├── configs/
│   ├── AutoStartHelper.apk         # 编译好的 2KB 开机自启动无线 ADB 极简应用
│   ├── factorytest_config_plain.xml # 明文配置模板（包含 setOrderPoint 注入命令）
│   └── factorytest_config.xml      # 已加密的工程测试配置（直接刷入 /sdcard/factoryTest/）
├── scripts/
│   ├── key_remap/                  # 机身实体按键长短按映射与电源控制工具包
│   │   ├── README.md               # 按键映射技术原理与配置说明
│   │   ├── enable_keys.cmd         # Windows 一键推送与激活批处理
│   │   ├── activate.sh             # GPIO 按键与总控激活脚本
│   │   ├── activate_adc.sh         # ADC 按键 (F10) 激活脚本
│   │   ├── toggle.sh               # GPIO 键行为分流 (电源/返回/主页)
│   │   ├── adc_toggle.sh           # ADC 键行为分流 (确认/最近任务)
│   │   ├── gpio_event_reader       # 456 字节极简事件解析二进制 (ARM)
│   │   ├── gpio_event_reader.S     # 汇编源码
│   │   └── *.idc / *.kl            # 输入设备属性与布局映射配置
│   ├── build_autostart_apk.py      # 纯 Python 生成 AutoStartHelper.apk 的构建脚本
│   ├── debloat.sh                  # 一键冻结 36 个电信/OTA/教育后台的优化脚本
│   ├── factorytest_crypt.py        # factorytest_config.xml 异或加解密工具
│   ├── fix_bilibili_ssl.sh         # 修复 B 站 BoringSSL 动态库冲突的热补丁脚本
│   └── restore_bloatware.sh        # 一键恢复所有被冻结组件的还原脚本
├── skills/
│   └── skyworth-c10h-modding/
│       └── SKILL.md                # 适用于 AI 编程助手的操作指南与自动化 Skill 定义
└── README.md                       # 本说明文档
```

### 快速上手指南

1. **第一次连接与解锁**：
   参考 [第三章](#三免-adb-破局网络流量劫持替换当贝桌面) 装入当贝桌面与 ES 文件浏览器。
2. **激活无线 Root ADB**：
   将 `configs/factorytest_config.xml` 上传至机器 `/sdcard/factoryTest/factorytest_config.xml`，点击一次桌面上的工厂测试图标。
3. **固化无线 ADB 并安装自启守护**：
   ```sh
   adb connect <设备IP>:5555
   adb install -r configs/AutoStartHelper.apk
   adb shell "toybox chattr +i /data/media/0/factoryTest/factorytest_config.xml"
   adb shell "pm disable com.yeker.factorytest.tool/com.yeker.factorytest.tool.broadcastReceiver.AppBroadcastReceiver"
   adb shell "pm uninstall -k --user 0 com.jsdx.speaker.launcher"
   ```
4. **一键系统瘦身与防 OTA**：
   ```sh
   adb push scripts/debloat.sh /data/local/tmp/
   adb shell "sh /data/local/tmp/debloat.sh"
   ```
5. **部署实体按键多功能长短按映射与息屏控制**：
   ```sh
   # Windows 电脑在仓库根目录直接执行批处理并传入设备 IP：
   scripts\key_remap\enable_keys.cmd <设备IP:5555>
   ```
   首次推送后即可脱离电脑使用；配置已写入 FactoryTestTool 自启流程，设备断电重启后依然自动生效。
