# 机身实体按键自定义重映射 (Physical Key Remap)

本目录包含针对创维天翼智慧屏 C10H (SK-L1001) 机身实体按键的重映射脚本与常驻守护工具。

由于设备原生没有标配遥控器，且系统缺少虚拟导航栏，机身上的三个物理按键（电源键、F9 键、F10 键）是操作设备的重要入口。通过本方案，可以在**不修改只读 `/vendor` 分区**的前提下，实现短按/长按分流与开机自启动。

---

## 1. 按键映射行为

| 物理按键 | 原始驱动设备 | 原始功能 / 扫描码 | 重映射后行为 | 判定阈值 |
|---|---|---|---|---|
| **原电源键** | `gpio_keypad` | `KEY_POWER` (116) | **短按：息屏 / 亮屏切换**（执行 `223/224`）<br>**长按：呼出原生关机与重启选项** | 松开判定：<0.6s 为开关屏，≥0.6s 呼出关机/重启菜单 |
| **F9 键** | `gpio_keypad` | 扫描码 67 | **短按：返回 (BACK / `keyevent 4`)**<br>**长按：主页 (HOME / `keyevent 3`)** | 松开时判定：< 0.6s 为返回，≥ 0.6s 为主页（长按不会误先触发返回） |
| **F10 键** | `adc_keypad` | 扫描码 68 (原静音) | **短按：确认 (CONFIRM / `keyevent 23`)**<br>**长按：最近任务卡片 (Recents)** | 松开时判定：< 0.6s 为确认，≥ 0.6s 打开 `RecentsActivity` |

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
3. **事件分流脚本 (`toggle.sh` & `adc_toggle.sh`)**：
   - 管道接收事件持续时间并判定时长，通过 `input` 或 `am` 执行对应操作。
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
5. **开机自启集成**：
   - 利用 `FactoryTestTool` 自启配置 `/sdcard/factoryTest/factorytest_config.xml` 中的 `<setOrderPoint>` 挂载自启命令：
     ```xml
     <setOrderPoint>(sh /data/local/codex-screen-toggle/activate.sh) &amp;</setOrderPoint>
     ```
   - `activate.sh` 会自动级联调用 `activate_adc.sh`，实现断电冷重启后所有按键监听与系统属性修正全自动上线。

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
