# 机身实体按键自定义重映射 (Physical Key Remap)

本目录包含针对创维天翼智慧屏 C10H (SK-L1001) 机身实体按键的重映射脚本与常驻守护工具。

由于设备原生没有标配遥控器，且系统缺少虚拟导航栏，机身上的三个物理按键（电源键、F9 键、F10 键）是操作设备的重要入口。通过本方案，可以在**不修改只读 `/vendor` 分区**的前提下，实现短按/长按分流与开机自启动。

---

## 1. 按键映射行为

| 物理按键 | 原始驱动设备 | 原始功能 / 扫描码 | 重映射后行为 | 判定阈值 |
|---|---|---|---|---|
| **原电源键** | `gpio_keypad` | `KEY_POWER` (116) | **短按：息屏 / 亮屏切换**（执行 `223/224`）<br>**长按：原生关机与重启选项**（零 JVM 开销极速呼出） | 按住达到 **0.35s** 原地立刻弹出关机/重启菜单；<0.35s 松手为开关屏 |
| **F9 键** | `gpio_keypad` | 扫描码 67 | **短按：返回 (BACK / `keyevent 4`)**<br>**长按：主页 (HOME / `am start Home`)** | 按住达到 **0.35s** 原地立刻回到桌面；<0.35s 松手为返回 |
| **F10 键** | `adc_keypad` | 扫描码 68 (原静音) | **短按：确认 (CONFIRM / `keyevent 23`)**<br>**长按：最近任务卡片 (Recents)** | 按住达到 **0.35s** 原地立刻呼出任务列表；<0.35s 松手为确认 |

---

## 2. 核心技术原理

1. **运行时动态重载 KeyLayout (`.kl`)**：
   - Android 系统支持从可写目录 `/data/system/devices/keylayout/` 加载按键映射。
   - 通过 Linux 设备模型总线接口向驱动发送 `unbind` 和 `bind` 命令：
     ```sh
     echo gpio_keypad > /sys/bus/platform/drivers/gpio-keypad/unbind
     echo gpio_keypad > /sys/bus/platform/drivers/gpio-keypad/bind

     echo adc_keypad > /sys/bus/platform/drivers/adc_keypad/unbind
     echo adc_keypad > /sys/bus/platform/drivers/adc_keypad/bind
     ```
     设备驱动重新绑定后，Android InputReader 会立即扫描并加载 `/data/system/devices/` 下自定义的 `codex_gpio_sleep.kl` 与 `codex_adc_keys.kl`，完全无需修改 `/vendor` 只读分区。
2. **微型原生事件监听器 (`gpio_event_reader`)**：
   - 采用纯汇编编写的极简 ARM 二进制（体积仅 456 字节，源码见 `gpio_event_reader.S`）。
   - 直接监听 `/dev/input/event*` 的 Linux `input_event` 结构体，精确计算按键按下到松开的微秒级时间差，输出 `PRESS / RELEASE / DURATION` 事件流。
3. **即时非阻塞长按分流 (`toggle.sh` & `adc_toggle.sh`)**：
   - 管道监听按下与松开事件。按住达到 **0.35 秒**（接近标准长按阈值）时**原地立刻触发长按动作**（手指无需松开即可看到菜单/主页弹出）；松手时自动清理状态且不误发短按，保证快速轻点返回与按住即长按的双重极致手感。
   - **零 JVM 启动延迟消灭**：传统 `input keyevent --longpress 26` 底层调用 Java `app_process`，每次冷启动 JVM 耗时高达 0.85s，导致长按卡顿。重构后直接调用底层已在内存常驻的 Activity 意图：
     ```sh
     am start -a com.android.internal.intent.action.REQUEST_SHUTDOWN --ez android.intent.extra.KEY_CONFIRM true
     ```
     响应耗时由 **870ms 断崖式压缩至 70ms（提升 12 倍）**，瞬间呈现原生带“重启”与“关机”的双键触控/遥控弹窗！基于 `/dev` 纯内存 tmpfs 状态标记与递增序列号机制，彻底杜绝快速连击下的误触竞争。
4. **系统级 Home 键崩溃与当贝桌面自杀式重载双重根治**：
   - **底层 Framework 崩溃修复**：原厂固件在 `/system/build.prop` 中写死了 `epg.launcher.packagename=com.tatv.android.TMC`。在精简冻结 TMC 后，原生框架 `PhoneWindowManager.startDockOrHome()` 调用 `pm.getLaunchIntentForPackage()` 返回 `null`，随后的 `intent.putExtra("GoHome", "true")` 导致未捕获异常崩溃中断按键派发。`activate.sh` 启动时自动纠偏指向当贝桌面：
     ```sh
     setprop epg.launcher.packagename com.dangbei.tvlauncher
     setprop sys.deflauncher.pkg com.dangbei.tvlauncher
     setprop sys.deflauncher.cls com.dangbei.launcher.ui.main.MainActivity
     ```
   - **拔除当贝自毁监听服务**：当贝桌面内置的 `HomeKeyEventCatchService` 会在收到 `CLOSE_SYSTEM_DIALOGS` 广播时强制执行 `launchApp("重启")` 并清空桌面位图缓存。`activate.sh` 与 `debloat.sh` 自动将其精准冻结：
     ```sh
     pm disable com.dangbei.tvlauncher/com.dangbei.launcher.service.HomeKeyEventCatchService
     ```
   - **原生 Home 栈 (`Stack #0`) 调度**：`toggle.sh` 中的长按采用 `am start -a android.intent.action.MAIN -c android.intent.category.HOME`，确保当贝桌面永远锚定在底层的 Home 栈中，主页切换与多任务返回耗时压缩至 **90 毫秒 ~ 200 毫秒**。
5. **开机自启与特权持久化集成**：
   - 传统方案中，`FactoryTestTool` 以 UID 1000 (`system`) 运行，缺少 Linux GID 1004 (`input`) 权限，无法读取 `/dev/input/event*`，且其后续执行的 `am force-stop` 会通过 cgroup (`killProcessGroup`) 连带强杀所有子进程。
   - 本项目逆向发现固件原生内置了 init 级特权服务 `telecom_shell`（运行于 `user root`, `group root`, PPID 1），通过向系统属性下发指令实现真正的 Root 常驻解耦：
     ```xml
     <setOrderPoint>setprop service.adb.root 1; setprop service.adb.tcp.port 5555; setprop persist.adb.tcp.port 5555; setprop ctc.sky.adbd_debug true; setprop persist.sys.usb.config mtp,adb; setprop sys.usb.config mtp,adb; setprop ctl.restart adbd; setprop ctl.start adbd; setprop sys.sky.ctcc.shell_1 "chmod 666 /dev/input/event0 /dev/input/event6"; setprop sys.sky.ctcc.shell_2 "/system/bin/sh /data/local/codex-screen-toggle/activate.sh"; setprop ctl.start telecom_shell; am start -n com.dangbei.tvlauncher/com.dangbei.launcher.ui.main.MainActivity; am force-stop com.yeker.factorytest.tool</setOrderPoint>
     ```
   - 保持 `/data/system/devices/idc/` 与 `keylayout/` 下配置持久化存在，系统开机由 Android `InputReader` 原生加载；守护进程由 `telecom_shell` 作为 Root 进程直接挂靠在 `init` (PID 1) 树下，免疫任何 `am force-stop`，完全实现冷重启与断电开机后所有物理按键重映射零人工干预自动上线。

---

## 3. 文件列表

- `activate.sh`: 激活 GPIO 实体键重映射，并将配置写入 `/data/system/devices/`，最后拉起 ADC 激活脚本。
- `activate_adc.sh`: 激活 ADC 实体键 (F10) 重映射。
- `toggle.sh`: GPIO 键逻辑分流（电源开关屏、F9 返回/主页）。
- `adc_toggle.sh`: ADC 键逻辑分流（F10 确认/最近任务）。
- `gpio_event_reader`: 456 字节的微型输入事件解析二进制。
- `gpio_event_reader.S`: `gpio_event_reader` 汇编源码。
- `gpio_keypad.idc` / `adc_keypad.idc`: 输入设备配置。
- `codex_gpio_sleep.kl` / `codex_adc_keys.kl`: 按键映射文件。
- `enable_keys.cmd`: Windows 一键推送与激活批处理脚本。

---

## 4. 手动部署与激活

在电脑连接 ADB 状态下，直接运行：

```bat
enable_keys.cmd [设备IP:5555]
```

或手动执行 ADB 命令：

```sh
adb shell mkdir -p /data/local/codex-screen-toggle
adb push . /data/local/codex-screen-toggle/
adb shell chmod 755 /data/local/codex-screen-toggle/activate.sh /data/local/codex-screen-toggle/activate_adc.sh /data/local/codex-screen-toggle/gpio_event_reader
adb shell sh /data/local/codex-screen-toggle/activate.sh
```
