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
5. **开机自启、独立监督（Supervisor）与高可靠安全机制**：
   - **执行树解耦**：利用固件原生 init 级服务 `telecom_shell`（以 `user root`, `group root`, PPID 1 运行），通过 `<setOrderPoint>` 系统属性下发，实现守护进程直接挂靠在 `init` 树下，彻底与 `FactoryTestTool` 的 cgroup 隔离，避免被后续的 `am force-stop` 连带清理。
     ```xml
     <setOrderPoint>setprop service.adb.root 1; setprop service.adb.tcp.port 5555; setprop persist.adb.tcp.port 5555; setprop ctc.sky.adbd_debug true; setprop persist.sys.usb.config mtp,adb; setprop sys.usb.config mtp,adb; setprop ctl.restart adbd; setprop ctl.start adbd; setprop sys.sky.ctcc.shell_1 "/system/bin/sh /data/local/codex-screen-toggle/activate.sh"; setprop ctl.start telecom_shell; am start -n com.dangbei.tvlauncher/com.dangbei.launcher.ui.main.MainActivity; am force-stop com.yeker.factorytest.tool</setOrderPoint>
     ```
   - **POSIX 原子硬链接单实例锁 (`ln` + `mv`)**：在 `supervisor.sh`、`toggle.sh` 与 `adc_toggle.sh` 中采用基于 POSIX 原子硬链接 (`ln "$tmpfile" "$lockfile"`) 的无竞争单实例锁。临时文件先写入 PID 再执行链接，从创建瞬间即具备所有权信息；残留死锁采用原子重命名 (`mv "$lockfile" "$lockfile.reclaim.$$"`) 回收，彻底消除了并发启动时的检查与清理竞争条件。
   - **故障退避机制（Backoff Throttling）**：`supervisor.sh` 监控子进程生命周期。若检测到子进程连续快速崩溃（如因硬件异常或文件缺失），自动触发阶梯式退避延迟（连续失败 >3 次延时 5 秒，>5 次延时 15 秒并报警），稳定运行满 60 秒后自动清零计数，彻底避免 CPU 空转狂飙。
   - **无损原地日志轮转（In-place Truncation）**：定时监控日志体积，当超过 200KB 时采用 `tail -n 300 ... > .tmp && cat .tmp > logfile` 原地覆盖截断，严格保留已有进程的文件描述符与 Inode，避免 `mv` 导致的孤儿写入与日志失联，覆盖 `supervisor.log`、`toggle.log`、`adc_toggle.log` 与 `events.log`。
   - **严格前缀比对的孤儿事件读取器防护**：通过解析 `/proc/[0-9]*/cmdline` 首部参数，精准核实 `$BASE/gpio_event_reader $DEVICE` 进程身份，杜绝 `pgrep -f` 全文模糊匹配误伤其他包含同名参数的系统命令或脚本。
   - **最小特权与原生权限保护**：完全保留 Android 原生 `/dev/input/event*`（`0660 root:input`）驱动权限，不进行任何非必要的 chmod；`chown` 严格仅作用于 `$BASE` 及指定的 4 个 `.idc`/`.kl` 文件，严禁递归越权修改系统公共目录 `/data/system/devices`。
   - **Supervisor 异常退出与单点故障恢复机制**：
     由于 `/vendor` 分区为只读 ext4 且 `vendor.rc` 将 `telecom_shell` 声明为 `disabled oneshot`，init 默认不会在 `kill -9` 后自动重拉 oneshot 服务。固件已提供双重可靠恢复入口：
     - **开机自动自愈**：每次重启时均由 `FactoryTestTool` / `telecom_shell` 全自动激活。
     - **手动/脚本即时唤醒**：若在调试过程中误杀 supervisor，无需重启设备，执行以下任一命令即可秒级无缝重拉：
       ```sh
       # 方式 1：通过原生 init 属性通道唤醒
       adb shell "setprop sys.sky.ctcc.shell_1 /data/local/codex-screen-toggle/activate.sh; setprop ctl.start telecom_shell"

       # 方式 2：直接执行激活脚本
       adb shell "sh /data/local/codex-screen-toggle/activate.sh"

       # 方式 3：Windows 批处理一键刷新
       enable_keys.cmd
       ```

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
