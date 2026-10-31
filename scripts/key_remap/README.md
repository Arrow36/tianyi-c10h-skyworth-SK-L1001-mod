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
5. **开机自启、独立监督（Supervisor）与特权解耦**：
   - **执行树解耦**：利用固件原生 init 级服务 `telecom_shell`（以 `user root`, `group root`, PPID 1 运行），通过 `<setOrderPoint>` 系统属性下发，实现守护进程直接挂靠在 `init` 树下，彻底与 `FactoryTestTool` 的 cgroup 隔离，避免被后续的 `am force-stop` 连带清理。
     ```xml
     <setOrderPoint>setprop service.adb.root 1; setprop service.adb.tcp.port 5555; setprop persist.adb.tcp.port 5555; setprop ctc.sky.adbd_debug true; setprop persist.sys.usb.config mtp,adb; setprop sys.usb.config mtp,adb; setprop ctl.restart adbd; setprop ctl.start adbd; setprop sys.sky.ctcc.shell_1 "/system/bin/sh /data/local/codex-screen-toggle/activate.sh"; setprop ctl.start telecom_shell; am start -n com.dangbei.tvlauncher/com.dangbei.launcher.ui.main.MainActivity; am force-stop com.yeker.factorytest.tool</setOrderPoint>
     ```
   - **独立监督进程 (`supervisor.sh`)**：采用单实例目录锁机制 (`mkdir run/supervisor.lock`)，每 2 秒核验两路按键监听进程的 `/proc/$PID/cmdline` 完整命令行，杜绝 PID 复用误判与双向互保竞争；一旦子进程异常退出，看门狗在 2 秒内受控重拉，并具备防抖回退机制。
   - **孤儿事件读取器防护**：在重拉监听器前自动核验并清理挂靠在 `event*` 上的旧 reader，杜绝多重监听导致按键二次触发。
   - **严格权限收紧**：配置目录遵循最小特权原则，脚本与安装目录由 `root:root 755` 保护，运行状态目录 `run/` 限制为 `700`，输入设备 `/dev/input/event*` 保持默认 `0660 root:input` 安全权限，无需任何非标放权。

---

## 3. 文件列表

- `activate.sh`: 激活脚本，收紧目录权限并部署 `.idc` / `.kl`，唤醒 `supervisor.sh`。
- `supervisor.sh`: 独立看门狗监督进程，维持 `toggle.sh` 与 `adc_toggle.sh` 高可靠运行并定时轮转日志。
- `toggle.sh`: GPIO 物理键处理（电源键短按息屏/长按呼出关机菜单，F9 短按返回/长按主页）。
- `adc_toggle.sh`: ADC 物理键处理（F10 短按确认/长按呼出最近任务）。
- `activate_adc.sh`: 兼容入口包装脚本。
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
