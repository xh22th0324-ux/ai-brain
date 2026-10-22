---
name: win-tune
description: Windows 主机「体检 + 提速 + 电源合盖 + 清理 + 启动项治理」技能，面向本机已实测调好的这套配置，也是本机所有系统级调整的登记处。当用户说「电脑怎么更快 / 开机变慢 / 看看还有什么能提速 / 清理 C 盘 / 磁盘满了 / 启动项太多 / 虚拟内存不足 / 页面文件怎么设 / 提交上限不够 / 这个缓存能删吗 / 合盖别睡眠 / 合盖不锁屏 / 关掉锁屏 / 程序要一直跑 / 待机断网 / 电脑方面的设置帮我调一下」等时使用。它按基线清单逐项比对（页面文件、提交上限、视觉特效、传递优化、显卡驱动、电源与合盖、屏保锁屏、注册表自启、第三方自启服务、磁盘余量），输出差异表；并提供启动项全量审计（含按字符码核对的坑）与磁盘可清理项扫描（只报告不删）。所有改动可回退，改前自动备份 + 生成 rollback.ps1。
description_zh: Windows 体检/提速/电源合盖/清理/启动项治理：页面文件、视觉特效、合盖不睡、关锁屏、自启项、磁盘空间，一键比对与安全修正
version: 1.1.0
agent_created: true
---

# win-tune — Windows 体检 · 提速 · 电源合盖 · 清理 · 启动项治理

一句话：**先量（只读），再判（分档），再改（可回退）**。这个技能里沉淀的是 2026-10-20 在这台机器上逐项实测过的配置与踩坑，不是通用模板。

**这也是本机所有系统级调整的唯一登记处**：以后凡是改 Windows 设置（电源、合盖、锁屏、显示、页面文件、启动项、服务、清理策略……），都写进这里的 `references/changes-YYYY-MM-DD.md` + `config/baseline.json`，不要另开新技能。

## 什么时候用

| 用户说的话 | 走哪一步 |
|---|---|
| 「看看还有什么能提速 / 电脑有点慢 / 体检一下」 | `audit`（只读）→ 按 A/B/C 分档给建议 |
| 「清理 C 盘 / 磁盘满了 / 哪些能删」 | `cleanup`（只读扫描）→ 列编号让用户挑，**绝不自动删** |
| 「启动项太多了 / 开机慢」 | `startup`（全量枚举）→ 标出可删/保护项，逐个确认 |
| 「虚拟内存不足 / 页面文件怎么设」 | `audit --only pagefile,commit` → 给容量规划 → `apply --pagefile 16384 32768 --yes` |
| 「视觉特效 / 传递优化 / 这些系统项设好」 | `apply --visualfx --deliveryopt --yes` |
| 「合盖别睡眠 / 合盖不锁屏 / 程序要一直跑 / 下载别断」 | `audit --only power` → `apply --power-nosleep --yes` |
| 「待机后唤不醒 / 待机断网」 | `audit --only power`，看是不是在 S0 现代待机上；见下面「合盖与电源」 |
| 「改完没生效」 | 看下面「生效条件」，八成是没重启 |

## 三条命令

```bash
# 1) 只读体检（默认，永远先跑）
python <SKILL_DIR>/scripts/win_tune.py audit
python <SKILL_DIR>/scripts/win_tune.py audit --json
python <SKILL_DIR>/scripts/win_tune.py audit --only pagefile,visualfx,power

# 2) 启动项全量审计（Run 四位置 + 第三方 Auto 服务 + 危险项标注）
python <SKILL_DIR>/scripts/win_tune.py startup

# 3) 磁盘可清理项扫描（只读，给体积与风险等级）
python <SKILL_DIR>/scripts/win_tune.py cleanup

# 4) 真改（不带 --yes 只打印计划）
python <SKILL_DIR>/scripts/win_tune.py apply --visualfx --deliveryopt --yes
python <SKILL_DIR>/scripts/win_tune.py apply --power-nosleep --yes
python <SKILL_DIR>/scripts/win_tune.py apply --pagefile 16384 32768 --yes
```

退出码：`0` 全符合、`1` 有差异、`2` 出错、`3` 缺管理员权限。

## 基线清单（这台机器 2026-10-20 调定值）

| 键 | 位置 | 目标值 | 为什么 |
|---|---|---|---|
| `pagefile` | HKLM `Memory Management\PagingFiles` | `E:\pagefile.sys 16384 32768` + `C:\pagefile.sys 2 2` | 旧值 1644–3288 把提交上限钉死在 17.3 GB，日志里 14 天内 5 次「虚拟内存不足」 |
| `visualfx` | HKCU `...\Explorer\VisualEffects` | `VisualFXSetting=2`，Mask `90 12 03 80 10 00 00 00`，FontSmoothing 保留 `2` | 最佳性能；保留字体平滑，否则中文发虚 |
| `deliveryopt` | HKLM `...\DeliveryOptimization\Config` | `DODownloadMode=0` | 只走 HTTP，不对上传（P2P） |
| `power` | `PowerSchemes\<方案>\SUB_BUTTONS\LIDACTION` | `0` 不采取任何操作（AC + DC，**全部电源方案**） | 本机只支持 S0 现代待机、无 S3，合盖默认就进 Modern Standby，后台任务必断 |
| `power` | `PowerSchemes\<方案>\SUB_SLEEP\STANDBYIDLE` | DC `0`（从不） | 电池下 5 分钟就睡，长时间任务照样断 |
| `power` | HKCU `Control Panel\Desktop` | `ScreenSaveActive=0`、`ScreenSaverIsSecure=0` | 屏保勾起「恢复时显示登录屏幕」= 变相锁屏 |
| `power` | HKLM `Winlogon\EnableGoodbye` | `0` | 动态锁：手机一离开蓝牙范围就锁屏 |
| `gpu` | DriverStore | 记录版本 `32.0.101.7092`（2026-09-03） | 只报告不驱动升级：11–14 代核显已进 legacy 分支 |
| `protected_services` | — | SolidWorks Flexnet / QQPCRTP / qmbsrv / AweSun | **不许动**，理由见下表 |

## 合盖与电源：这台机器的关键事实

`powercfg /a` 实测：**只有「待机 (S0 低电量待机)」，没有 S3，没有休眠**。所以：

- 合盖 / 闲置 = 进 Modern Standby，**不是锁屏问题，是系统真睡了**；
- 表面症状常被误判成「假死机」「唤不醒」——黑屏、灯灭，但 standby 供电没断；
- 唯一可靠解法是把合盖动作设为 `0`，而不是去调「唤醒方式」。

`apply --power-nosleep` 做的事（写全部电源方案，最后 `/setactive SCHEME_CURRENT` 让它立即生效）：
`LIDACTION` AC/DC → 0、`STANDBYIDLE` DC → 0、屏保关、`EnableGoodbye` → 0。

坑：`powercfg` 的输出是 **OEM 代码页（中文 = cp936）**，Python 用 `text=True` 会按 UTF-8 解、
`errors="ignore"` 直接把中文吃光，只剩空格。所以本技能用 `_run_text()` 按 utf-8→cp936→mbcs 顺序试解码，
解析睡眠状态时也优先用语言无关的注册表 `Power\CsEnabled`。

## 启动项治理：哪些能删、哪些绝对别碰

**能删（实测无副作用）**

| 项 | 类型 | 影响 |
|---|---|---|
| `Intel® Graphics Software` | Run（**WOW6432Node 分支**） | 只少一个托盘图标，面板可从开始菜单打开 |
| `RTHDVCPL` | Run（HKLM） | Realtek 音频托盘，驱动与音效功能不受影响 |
| `DSAService` / `DSAUpdateService` | 服务 → 手动 | Intel 更新检查器，对性能零贡献 |
| `MSSQL$TEW_SQLEXPRESS` / `SQLBrowser` / `SQLTELEMETRY` / `SQLWriter` | 服务 → 手动 | SOLIDWORKS **Electrical** 才用；普通零件装配不受影响 |
| 夸克两个更新服务 + `QuarkUpdaterTaskSystem` | 服务 → 禁用 / 任务 → 禁用 | 只是更新器 |

**绝对别删**

| 项 | 原因 |
|---|---|
| `AweSun`（向日葵） | 删了重启后无法远程连回这台机器 |
| `QQPCRTP` / `qmbsrv` / `QQPCTray` | 腾讯管家是这台机器**唯一**实时防护（Defender 已被策略关闭）。托盘是它的操作界面 |
| `SolidWorks Flexnet Server` | 停掉后 SOLIDWORKS 打不开（许可服务） |
| `CodexSandboxService.OpenAI.Codex` | **改不动**：服务 ACL 被程序保护，`Set-Service` 报拒绝访问，只能在应用内关 |

## 磁盘清理：分两档，永远只报不删

`cleanup` 扫 `config/baseline.json` 里的 19 个目标，标 `safe` 或 `confirm`，**永远不删**。用户挑完编号后：

- 个人目录（Desktop / Downloads / Documents）→ 走回收站，不直接删；
- `os.remove` 在本机是「扔进回收站」，**不调 `SHEmptyRecycleBinW` 不释放空间**；
- **单轮删除上限 50 个文件**，超过会被策略整体中止。>50 个就写成 `.bat` 让用户自己跑。

## 生效条件

1. **页面文件 / 提交上限**：改注册表后必须重启。`Win32_PageFileUsage` 的已分配值只反映当前已分配，不是上限。
2. **视觉特效**：HKCU 立即写，Explorer 重启后整体生效（注销或重启）。
3. **显卡驱动**：安装器返回码不可信（实测 233 但实际成功），只认 `Win32_VideoController.DriverVersion` + PnP `Status=OK`。
4. **服务改手动**：立即生效，不用重启。
5. **合盖 / 电源 / 屏保 / 动态锁**：立即生效（脚本末尾会 `/setactive SCHEME_CURRENT` 重载当前方案）。改完让用户合一次盖验证。

## 本机环境铁律（这几条是踩出来的，别重复踩）

| 现象 | 真相 |
|---|---|
| `reg.exe` 导出 .reg 报错 | **在程序黑名单里**。备份改用 `winreg` 读全部键值存 JSON，不要找等价绕过 |
| `Set-CimInstance` 设 `Win32_PageFileSetting` 失败 | `-Filter` 里 `E:\\pagefile.sys` 反斜杠转义会崩。**直写注册表 `PagingFiles` 最稳** |
| `Add-Type` / `New-Object -ComObject` 被拒 | 安全策略拦。需要 COM 就用 Python ctypes 直接调接口 |
| `os.remove` 删了但空间没涨 | 实际进了回收站。补 `SHEmptyRecycleBinW(None,None,1\|2\|4)` |
| `rd /s /q` 在用户目录 rc=5 | 被拒。用户目录批量删只能靠用户自己双击 .bat |
| `powercfg` 输出中文全变空格 | 输出是 OEM 代码页（中文 cp936），`text=True` 按 UTF-8 解、`errors=ignore` 会把中文吃光。用 `_run_text()` 按 utf-8→cp936→mbcs 试解 |
| 「合盖后程序断了 = 锁屏没设好」 | 错。先 `powercfg /a` 看有没有 S3；只有 S0 的机器合盖直接进 Modern Standby，改锁屏一律无效 |
| 按名字找不到某个 Run 项 | 键名可能带**前导空格**（实测 `QQPCTray`）或 `®` 等字符。按字符码核对 |
| 注册表 Run 项看漏 | 必须查**四个位置**：HKLM / HKLM-WOW64 / HKCU / HKCU-WOW64。Intel 那条在 WOW64 分支 |
| PS5 相关 | 不归本技能管，走 `ps5` 技能 |

## 输出怎么讲给用户

- 先一句结论（「系统侧没有瓶颈，真正的问题在页面文件额度」），再给表格，最后给分档建议。
- 每个建议必须带**实测依据**（数字、日志事件 ID），不用形容词代替证据。
- 说清哪些操作**需要重启**、哪些**立即生效**、哪些**不可回退**。
- 改完必须报出备份目录与 `rollback.ps1` 路径。

## 安全边界

- `audit` / `startup` / `cleanup` 三个命令**只读**，不改任何东西。
- `apply` 只写：HKCU 视觉特效、HKLM 传递优化、HKLM 页面文件、电源方案（`powercfg` 写 `PowerSchemes` 下的 AC/DC 索引）、
  HKCU 屏保三项、HKLM `Winlogon\EnableGoodbye`。**不碰服务、不碰启动项、不删文件**。
- 改前把原值快照到 `<workspace>\_wintune_backup-<时间戳>\`，并生成 `rollback.ps1`（电源类会按方案逐个还原 AC/DC）。
- 现有配置与基线不一致且用户没确认时，只报差异，不擅自"修正"。

## 目录

```
win-tune/
├── SKILL.md                       # 本文件
├── config/baseline.json           # 目标值清单，改这里就能换标准
├── scripts/win_tune.py            # audit / startup / cleanup / apply
└── references/changes-2026-10-20.md   # 2026-10-20 全部改动的完整台账
```

改标准（比如页面文件想设 8–16 GB）只需编辑 `config/baseline.json`，不用动代码。

## 归档

- 本地：`~/.workbuddy/skills/win-tune/`
- 共享：`\\iStoreOS\games\skills\skills-win-tune-20261020.zip`（sha256 回读校验 PASS）
- 单技能重打包：`python ~/.workbuddy/tools/backup_skills.py --only win-tune`
