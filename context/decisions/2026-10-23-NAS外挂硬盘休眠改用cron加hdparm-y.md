---
title: NAS 外挂硬盘休眠：三个标准方案都失效后的自制方案
date: 2026-10-23
tags: [nas, 硬盘, 休眠, hdparm, hd-idle, usb桥接, 排障, istoreos]
status: settled
source: claude
---

# 决策：用 cron 监控 + `hdparm -y` 实现空闲休眠

**结论**：`hdparm -S` 和 `hd-idle` 在这块盘上**都无效**。
唯一有效的是 `hdparm -y`（SCSI START STOP UNIT），所以自己用 cron 计时，到点调它。

## 背景

iStoreOS 上一块 WD 外置盘（`/dev/sdb`，ext4，SMB 当文件库），
想设成"空闲 2 小时后休眠"。用户先后装、又卸了应用中心的「硬盘休眠」插件。

同时有个矛盾：这块盘**通电将近一年**，但 SMART `Power_On_Hours` 只有 **734 小时**。

## 演进过程（三次翻车，每次都"命令成功但盘没睡"）

### 第一次：以为插件多余，改用 `hdparm -S`

推理是：`hd-idle` 只能催睡、不能调长，而 `hdparm -S` 能把计时器写进盘，一劳永逸。

实测 `hdparm -S 244` **返回成功**。加上体检显示：60 秒零 I/O、
强制 `hdparm -y` 第 2 秒进 standby 且 60 秒没醒 —— 看起来方案成立。

于是写进 `rc.local` 固化，还特意按**型号**匹配而不是 `sdX`。

### 第二次：2 分钟短测推翻一切

`hdparm` 没有读取 `-S` 值的选项，为了验证，把时间临时改成 2 分钟（`-S 24`），
每 15 秒用 `hdparm -C`（只查询、不唤醒）看状态。

**结果：180 秒一直 `active/idle`，一次都没睡。**

同时取证排除了干扰项：
- 30 秒 `/proc/diskstats` 读写均为 **0** —— 盘完全空闲，不是被 I/O 吵醒
- `dmesg` 无 ext4 recovery —— 不是重启后日志重放
- `hdparm -I` **能读到完整 IDENTIFY**（`WDC WD30EZRX-00D8PB0`）—— 桥接确实透传 ATA

**这三个事实同时成立，只能是 `hdparm -S` 假成功。**

### 第三次：`hd-idle` 也不触发

按 OpenWrt 官方文档装 `hd-idle`，配置 2 分钟验证：

```
/usr/bin/hd-idle -d -i 0 -a sdb -i 120
```

参数完全正确（全局禁用 + 单盘 120 秒）、进程在跑、盘确实空闲 ——
**150 秒后仍然 `active/idle`**。

### 最终：自己计时

既然只有 `hdparm -y` 有效，就用最简单的办法：读 `/proc/diskstats` 判断有没有 I/O，
连续空闲够久就调一次 `hdparm -y`。十几行 shell + 一条 cron。

**自测通过**：把状态时间戳伪造成"120 分钟前有过 I/O"，手动跑一次监控脚本，
盘立刻进入 `standby`。

## 根因：SCSI 桥接只认 START STOP UNIT

| 命令 | 协议层 | 此盘是否支持 |
|---|---|---|
| `hdparm -I` | ATA PASS-THROUGH | ✅ 能读完整 IDENTIFY |
| `hdparm -y` | SCSI `START STOP UNIT` | ✅ 立刻停转 |
| `hdparm -S` | ATA `IDLE`（无 SCSI 映射） | ❌ **返回 0，实际不转发** |
| `hd-idle` | 内部发 spindown-now | ❌ 实测不触发 |

**关键认知**：`hdparm -I` 能读到 IDENTIFY **不代表**其他 ATA 命令也能透传 ——
它们是不同的 opcode。这一点极易误判。

## 选项对比

| 方案 | 结果 |
|---|---|
| 应用中心「硬盘休眠」插件 | 只能催睡，且实测不触发 → 放弃（已卸载） |
| `hdparm -S` + `rc.local` | **假成功**，命令返回 0 但盘不睡 → 放弃 |
| `hd-idle` + uci 配置 | 参数正确也不触发，且设备名写死 → 放弃 |
| **cron + `hdparm -y`** | **采用**：路径已验证有效，逻辑全可见 |

## 实施要点

```sh
# /usr/bin/disk-sleep-check.sh（cron 每 5 分钟调用）
DEV=""
for d in /sys/block/sd*; do
    grep -qi elements "$d/device/model" 2>/dev/null && DEV=$(basename "$d") && break
done
[ -z "$DEV" ] && exit 0

cur=$(awk -v d="$DEV" '$3==d {print $4+$8}' /proc/diskstats)
if [ "$cur" != "$last_io" ]; then 记录时间; exit 0; fi
if [ 空闲 >= 阈值 ]; then hdparm -y "/dev/$DEV"; fi
```

**三个设计要点**：

1. **按型号匹配设备，不写死 `sdX`。**
   实测重启后盘从 `sdc` 变成了 `sdb`。若写死设备名，`rc.local` 会静默失效——
   用户永远发现不了。

2. **I/O 计数用次数（`$4+$8`），不用扇区数（`$6+$10`）。**
   2.8TB 盘的扇区数会超过 awk 安全整数范围，`print` 可能输出科学计数法，
   导致字符串比较永远"不相等"，逻辑永久失效。

3. **状态文件放 `/tmp`。**
   重启清空即重新计时，符合"重启后不该立刻睡"的预期。

**精度**：受 cron 间隔限制，设 120 分钟实际在 120~125 分钟内入睡。
想更准就缩短检查间隔，但没必要。

## 可逆性

- **完全可逆**：`sh cron_sleep.sh 0` 移除 cron 行、监控脚本和状态文件。
- **重新评估信号**：
  - 换了支持 ATA IDLE 的硬盘盒 → 先跑 `verify_sleep.sh`，若 2 分钟内睡了，
    就该改回 `hdparm -S`（更简洁，无需常驻进程）
  - 盘改成频繁访问（下载盘 / 媒体库实时索引）→ 应设 `0` 一直转

## 影响范围

- 设备：iStoreOS (x86_64, 24.10.8)，`/dev/sdb` = WD30EZRX 3TB + Elements USB 桥接
- 工具：`tools/hdd_sleep_diag.sh`（体检）、`tools/verify_sleep.sh`（验证）、
  `tools/cron_sleep.sh`（实现）
- 已停用：`hd-idle` 服务（stop + disable）；已移除 `rc.local` 里的 `hdparm -S` 块

### 部署后在机器上的实际状态（便于以后核对）

| 项 | 值 |
|---|---|
| 空闲阈值 | 120 分钟 |
| 检查间隔 | 5 分钟（实际入睡 120~125 分钟） |
| 监控脚本 | `/usr/bin/disk-sleep-check.sh` |
| cron 行 | `*/5 * * * * /usr/bin/disk-sleep-check.sh`（在 `/etc/crontabs/root`） |
| 状态文件 | `/tmp/.disksleep.state`（`<I/O次数> <时间戳>`，重启清空） |
| 执行动作 | `hdparm -y` |
| 已停用 | `hd-idle`（stop + disable）、`rc.local` 的 SETSLEEP 块 |
| 备份 | `/etc/rc.local.bak.*` 若干份，改前的原始版本 |

**不需要重启**：cron 任务写入即生效，`crond` 已在运行，
`/etc/init.d/cron enable` 已保证开机自启。

## 顺带解开的疑点

`734 / 8760 = 8.4%` —— 这块盘 **91.6% 的时间在 standby**，而 SMART 通电计时在
standby 时不走。所以"通电一年"与"734 小时"**不矛盾**，它不是因为新，而是一直在睡。

> 教训：看到 `Power_On_Hours` 偏低，先算 `小时数 / 装机时长`，别直接下"盘很新"的结论。
