# PS5 越狱环境与「自制载荷跑不起来」（13.60 实测）

> 场景：想跑温度/风扇/帧率监控、跑 hwinfo、跑 etaHEN，结果载荷一启动就崩，
> 或者「面板上显示已加载」但功能完全没有。
> 本文档给一套**判定顺序**和**已实测的结论**，省掉反复试错。
>
> ⚠️ **本文档在 2026-10-17 做过一次重要修正**：早期结论「13.60 上这类载荷无解」
> 已被实机推翻（§6）。崩溃签名（§3）只说明**这个载荷**初始化放弃，不能推出**环境没能力**。

---

## 1. 先搞清楚这台机器在跑什么

**最可靠的清单**不是面板 UI，而是内核日志里的 FMEM 行。连 klogsrv（3232）抓一段即可：

```
<118>[SceShellCore] FMEM   7.5/  20.9   0.0/   0.0 kstuff.elf
<118>[SceShellCore] FMEM   3.8/  16.8   0.0/   0.0 nanodns.elf
<118>[SceShellCore] FMEM  23.9/  37.3   0.0/   0.0 shadowmountplus.elf
```

配套端口探测（`scripts/ps5ftp.py` 或直接 socket）：

| 端口 | 服务 | 归属 |
|---|---|---|
| 2121 | ftpsrv | ps5-payload-dev/ftpsrv |
| 3232 | klogsrv | klog 转发（读 `/dev/klog`） |
| 9021 | elfldr | 载荷加载器 |
| 9100 | ps5-exporter | **温度/风扇指标 HTTP 端点**（§6） |
| 8086 | Cooling System Center | 网页界面（§7） |
| 1337 / 9081 / 9090 | FTP / klog / 直装 pkg | **etaHEN 专属**，它没起来就一定是 closed |
| 8770 | PS4Mount 面板 | 只在 PS4Mount 运行时 |

---

## 2. etaHEN 在 13.60 上起不来（2026-10-17 实测）

固件 13.60 对应的是 2026-09 才公开的 Relapse 链；本机那份 `etaHEN 2.5B`
（2025-12-25 构建）**没有 13.60 支持**，点启动后表现为：

| 判据 | 实测结果 |
|---|---|
| 专属端口 1337 / 9081 / 9090 / 8000 / 12800 | **全部 closed** |
| klog 的 FMEM 进程表 | **没有 etahen 进程** |
| `/data/etaHEN/*.log` 的 mtime | 停在旧日期，今天一个字没写 |
| hwinfo / etaHEN 载荷是否真的被 exec 过 | **是的**（见 §3，有新 SIGILL） |

→ **结论：UI 说「已加载」不等于起来了。** 三条一起查，别只信面板。

**注意版本节奏**：etaHEN 官方 GitHub 到 2026-10 仍然只发到 **2.5B**（2025-12-25），
官方渠道没有 13.60 版本；社区侧线（OnionHEN，见 §7）已自行做出 13.60 支持。
所以「13.60 没有 etaHEN」这句话只对**官方 etaHEN** 成立，别外推成「13.60 什么都跑不了」。

---

## 3. 「privileged instruction fault」崩溃签名（关键）

elfldr 和 pldmgr 注入载荷都是**同一条路**：劫持系统进程 `SceSpZeroConf`
（`NPXS40112`），在它里面跑 `payload.elf`。所以两种加载器崩出来的现场是同一套。

klog 里的形态：

```
# signal: 4 (SIGILL)
# thread name: SceSpZeroConfMain
# proc name: payload.elf
# reason: privileged instruction fault
# rbx: 0000000200474000        <- 载荷镜像基址（大小成正比，可用来认载荷）
```

**崩在哪条指令**：把 `rbx` 当基址、`rip - base` 当偏移，去 ELF 里取字节，看到的是

```
0f 0b            ud2           <- rip 停在这里
```
紧邻前面固定是这一段：
```
48 8b 05 ..      mov rax,[rip+x]     ; 取函数指针
48 8b 49 28      mov rcx,[rax+0x28]
8b 39            mov edi,[rcx]
ff d0            call rax            ; 调用
0f 0b            ud2                 ; 调用"不该返回"却返回了 → 主动 trap
```
这是 **SDK 运行时的「初始化失败 → `__builtin_trap()`」路径**，不是坏字节、不是加载器传参错。

### 3.1 但它**不能**证明「环境没能力」（重要修正）

同一个 ud2 现场，至少对应两种完全不同的成因：

| 成因 | 判别方法 |
|---|---|
| **A. 载荷用老 SDK 构建，启动代码不认识这版固件** —— SDK 的启动代码带固件偏移表，表里没有的固件**根本进不到 `main()`**，所以既不打印、也不报错，只是崩 | 换一个**明确声明支持 13.60** 或**用 SDK ≥ v0.42 构建**的同类载荷；能跑通即证明是构建问题 |
| **B. 载荷要内核级接口提权失败**（`kernel_get_ucred_attrs` / `kernel_set_ucred_caps`），kstuff 的 fpkg 补丁给不了 | 换不需要提权的载荷对照（§6 的 exporter 就是纯库调用、不提权） |

> 教训：别看到 ud2 就写「无解」。**ud2 是载荷在放弃，不是主机在拒绝。**
> 2026-10-17 就是靠这条翻案的：同一个 ud2 签名，换成新构建的 exporter 立刻跑通。

---

## 4. elfldr 的 `MSG_PEEK` 坑（差点误判成"加载器坏了"）

elfldr v0.26 在握手时用 `recv(..., MSG_PEEK | MSG_WAITALL)`，在这版固件的 socket 实现上
直接返回 `EINVAL`，日志里是：

```
<118>[elfldr.elf] socksrv.c:246:recv: Invalid argument
```

连接被丢弃、载荷根本没被读进来。**规避很简单**：连接成功后等 **1～1.2 秒**再 `sendall()`，
让 elfldr 的 recv 先就位。改造后同一个 ELF 立刻能被 exec（然后按 §3 崩，那是另一回事）。

> 教训：看到一行 `EINVAL` 不要立刻下「加载器不兼容」的结论——先做一次
> 「等一秒再发」的低成本对照，能立刻区分「时序问题」和「真的不兼容」。

---

## 5. 往 pldmgr 里手动塞载荷，点不动（已实测）

`pldmgr` 只认它自己登记过的条目：
- `payloads/repo/<id>@<hash>/` —— 从仓库下载的，**能点能启**；
- `payloads/local/<id>/` —— 手工放入 `meta.json` + `xxx.elf` 后，
  列表里**能看到**，但点启动**毫无反应**（klog 里一条记录都没有）。

→ 想让某个 ELF 在 pldmgr 里一键启，得走它的仓库/正式安装流程；
手工塞进去的只适合当「存档 + 用 elfldr 发」。

**但自启是另一条路**：`/data/pldmgr/autoload.txt` 里写 `local/<id>`，pldmgr 启动时会按行 exec
该目录下的 ELF（走的是加载器逻辑，不是 UI 点击逻辑）。给非仓库载荷做开机自启应该用这条，
见 §7.1.7（OnionHEN 已按此法配置，待冷启动验证）。

`meta.json` 最小可用形状（供参考，不保证可启动）：
```json
{ "schema": 2, "kind": "local", "filename": "x.elf", "installed_at": "...",
  "id": "x", "name": "x", "version": "0.1", "description": "...",
  "author": "...", "category": "Tools", "checksum": "" }
```

---

## 6. ✅ 已实测跑通：13.60 看温度（ps5-exporter）

**2026-10-17 在 CFI-1018B / 13.60 上实测**，全程不需要 etaHEN、不需要提权。

- 项目：`Marice/ps5-exporter`，tag **v0.2.0**（2026-10-06），资产 `ps5-exporter.elf`（155,352 B）
- 作者自述：*Verified on a CFI-7121 running firmware 13.60*，且明确写了
  **「These are ordinary library calls, not kernel memory reads at fixed offsets」**
  —— 也就是**不吃固件偏移表**，这正是它能跨版本的原因
- 传输：elfldr 9021（**必须等 1~1.2 秒再发**，见 §4）
- 端口：**9100**（可用 `EXPORTER_PORT` 改），端点 `GET /metrics`，`GET /quit` 可卸载

实机拿到（空闲态）：

```
ps5_info{model="CFI-1018B 01",firmware="13.60",system_version="13.590.001"} 1
ps5_temperature_celsius{sensor="cpu"} 44
ps5_temperature_celsius{sensor="soc0"} 42      # soc0..soc15 全在 40–44
ps5_cpu_frequency_hertz 2560000000
ps5_fan_duty_ratio 0.1855
ps5_uptime_seconds 5132
```

共 **31 个指标族**：17 路温度、风扇占空比、CPU 频率、每进程 CPU/内存、
各分区容量、SMP 游戏库与挂载状态、开机时长等。
（它自述在 13.60 上被拒绝的有：每核 CPU、SoC 功耗、内存 sysctl —— 这些自动留空，不影响温度。）

**发送脚本**（已落盘，改 `HOST` 即可复用）：

```python
# send_exporter.py 关键三步
c = socket.socket(); c.settimeout(20); c.connect((HOST, 9021))
time.sleep(1.2)                 # 必须：否则 §4 的 EINVAL
c.sendall(open('ps5-exporter.elf','rb').read())
```

**注意**：载荷不持久，重启后要重发；`pldmgr` 手工塞的条目点不动（§5），
要开机自动跑得让它进 autoload 正规流程，或写进 Relapse 的 payload 选择列表。

---

## 6.1 「CPU 78 ℃ 正常吗」——读数怎么判读（2026-10-17 实测基线）

拿到数字只是第一步，**判读必须把温度和风扇占空比一起看**，否则会把「正常的高位」
当成故障（78 ℃ 在 3A 游戏里很正常），也会把「风扇已经在 80% 还压不住」这种真问题当成正常。

### 6.1.1 本机基线（CFI-1018B / 13.60，室温按 ~22 ℃ 估，未实测）

| 场景 | `{sensor="cpu"}` | `soc0..15` | 风扇 duty |
|---|---|---|---|
| 空闲 / 主页 / 看视频 | 44 ℃ | 40–44 ℃ | 18.55 % |
| **原生 PS5 3A（《羊蹄山之魂》）** | 运行中某次采样 68 ℃ / **用户观察峰值 78 ℃** | 61–67 ℃ | **18.55 %** |

关键：**峰值 78 ℃ 时风扇只有 18.55 %（空闲与游戏两态实测同为此值 = 风扇根本没提速）**
→ 散热系统还有极大余量，这属于「芯片热、但热被顺利带走了」的健康状态。

### 6.1.2 判读区间（APU / SoC）

```
35–50 ℃   待机、主页、视频
50–70 ℃   一般游戏、PS4 游戏经 PS4Mount
70–82 ℃   原生 PS5 3A 大作的高位 —— 正常，不必处理
82–88 ℃   偏高，开始留意（同时看风扇是否已 >50 %）
88–95 ℃   SoC 开始降频保护，查积灰/摆放/室温
≈105 ℃   硬件强制关机线（保护动作，说明散热已失效）
```

判定口诀：**温度高不高看绝对值，正不正常看「风扇还剩多少余量」。**
风扇 <25 % 就 78 ℃ → 无事；风扇 >60 % 才 78 ℃ → 散热在吃力，去清灰。
风扇长期 70–80 % 仍压不住、或出现掉帧/花屏/「主机温度过高」提示/自行关机 → 必须处理。

### 6.1.3 三个容易误判的坑

1. **不能拿 PS4 游戏的读数当基线。** PS4 游戏（经 PS4Mount）在 PS5 上只用到一部分算力，
   同样室温下只有 44–65 ℃；换到原生 PS5 大作跳到 78 ℃ 是**负载变了**，不是机器变差了。
2. **`sensor="cpu"` 只是 17 路里的一路。** 真实热区参考取
   `max(cpu, soc0..soc15)`；本机峰值时最高那一路是 soc6/soc7（67 ℃）。
3. **室温是最大变量。** 环境温度每高 5 ℃，同一游戏的读数大致 +3–5 ℃。夏季 30 ℃ 室温下
   同一个游戏冲到 85 ℃ 是可预期的，别按冬天的数字下结论。

一条命令看全量：`curl -s http://<IP>:9100/metrics | grep -Ei "temp|fan"`

### 6.1.4 需要动手的信号（按优先级）

| 症状 | 先查什么 |
|---|---|
| 风扇声音突然变尖锐、持续高转 | 机身背后积灰（进气口/散热鳍片）、是否贴墙 <10 cm、是否在密闭柜内 |
| >88 ℃ 仍不降 | 同上；若已清灰且摆放正常，考虑液金/硅脂老化（需拆机，别自己上） |
| 掉帧 + 温度高同时出现 | 看 `ps5_cpu_frequency_hertz` 是否被压到 2.56 GHz 以下 → 已在降频 |
| 出现「主机温度过高」提示或自行关机 | 立即停机冷却，按上表逐项排查；反复出现则送修 |

---

## 6.2 磁盘占用盘点与清理（FTP 实操，2026-10-17 实测）

问「有没有无用的软件在占资源」时，**先把「内存」和「磁盘」分开**：载荷进程通常只有几十 MB
（实测 kstuff 7.5 / nanodns 3.8 / SMP 23.9 MB，合计 <100 MB），16 GB 机器上完全不是瓶颈；
真正会堆起来的是磁盘和日志。

### 6.2.1 三个必须先知道的坑

| 坑 | 现象 | 处理 |
|---|---|---|
| `ps4mount/log.txt` **无限追加** | 本机跑两天就 13.9 MB / 112,308 行，其中 **26,058 行是同一句** `process_mount.cpp at 8177` 错误（它把 klog 转发进来，不过滤重复） | 定期裁剪到最近 500 行即可，见 6.2.2 |
| **`DELE` 返回 `226` 而不是 `250`** | `ftplib.delete()` 抛 `error_perm: 226 File deleted`，看着像失败 | **文件其实已经删掉了**。判据是随后 `LIST` 里消失；别因为异常就重试或用别的办法硬删 |
| **`RMD` 对非空目录失败** | 直接 `rmd` 报错 | 必须自写递归：先 `DELE` 全部文件、处理子目录，再 `RMD` |

### 6.2.2 裁剪一个正在被写的大日志（安全做法）

PS4Mount 用 **append 模式**打开 `log.txt`，所以「下载 → 取尾部 → `STOR` 覆盖」是安全的：
覆盖后它的下一次写从 0 偏移继续，不会留下 13.9 MB 的稀疏空洞。

```text
1. FTP 下载 log.txt 到本地（当备份）
2. 取最后 500 行写成新文件
3. STOR 覆盖远程 /data/ps4mount/log.txt
4. 等 30–40 s 再 LIST：大小应保持在新值附近。
   若一口气回涨到原大小 → 这个版本的写方式是保持 fd 偏移（非 O_APPEND），
   那就只能等下次重启 PS4Mount 前删掉，别硬来。
```

### 6.2.3 本机 /data 体积基线（CFI-1018B，2026-10-17）

```
分区：total 625 GiB / free 125.6 GiB / **avail 37.5 GiB**
     ⚠️ /data、/data/homebrew、/data/etaHEN/games 是同一个 nullfs，可用空间是同一份
游戏（都在用，别删）：
  /data/homebrew/PPSA26344.exfat        188.0 GB   （镜像，SMP 库）
  /data/etaHEN/games/PPSA08560          149.8 GB   （Split Fiction，文件夹格式，SMP 库）
  /data/homebrew/PPSA14708.exfat         28.6 GB   （镜像，SMP 库）
工具目录：
  pldmgr 33.2 MB / OnionHEN 29.9 MB / ps5upload 3.3 MB / shadowmount 3.7 MB
  ps4_autoloader 3.3 MB / hwinfo 0.26 MB / pkgmgr 0.34 MB
```

判断「这是不是垃圾」的顺序：**先看它是否在自启链或 SMP 游戏库里**（§5 的
`ps5_autoloader/autoload.txt` + `pldmgr/autoload.txt` + `/data/homebrew` 与
`/data/etaHEN/games` 下的镜像/文件夹），在链上的一个都别动；不在链上的才是候选。

### 6.2.4 清理纪律（本机已执行过一次）

```text
1. 先在本地建 _backup_<日期>/，把要删的每个文件下回来并**逐文件比对大小**
2. 再递归删除（DELE 抛 226 属正常）
3. 事后 LIST 核对：pldmgr/payloads/local 只应剩下真正在用的条目
4. 大件（游戏镜像/文件夹）永远先问用户，绝不代删
```

2026-10-17 实删清单（约 20 MB，全部有本地备份）：
`payloads/local/` 下的 `13`（13.6 专用 SMP）、`ceshi-kstuff`、`kstuff-lite`、
`ps5-backpork`、`web-file-mgr`、`hwinfo-sysinfo`、`hwinfo-bench`，加 `/data/hwinfo/`，
以及把 `ps4mount/log.txt` 从 13.9 MB 裁到 66 KB。

---

## 7. 备选方案（都声称/实测支持 13.60）

| 方案 | 形态 | 能看什么 | 前提 |
|---|---|---|---|
| **ps5-exporter** v0.2.0 | ELF，HTTP 9100 | 温度 17 路、风扇、频率、进程、存储 | 只要 elfldr（**本机已实测通过**） |
| **OnionHEN** v0.9.0（2026-10-15） | ELF，4.6 MB，基于 etaHEN | **电视端游戏 overlay**：FPS / CPU / GPU / RAM / 温度 / 网络；工具箱、风扇阈值、金手指 | 需 elfldr 9021 做第一跳；**本机 13.60 已实测通过**，配方见 §7.1 |
| **PS5 Cooling & System Center** v1.68.1（2026-10-15） | ELF 9 MB + 可选 pkg | 网页界面 **:8086**，温度/风扇曲线、按游戏风扇策略、传感器诊断、PS4Mount 集成 | 作者测于 12.00，*多位用户报告 13.60 可用*；风扇控制依赖 kstuff |

三者优先级建议：**只想看数字 → exporter（最轻、已验证）；想要电视上实时 overlay → OnionHEN（§7.1）；
想要风扇曲线/长期记录 → Cooling Center**。

---

## 7.1 ✅ OnionHEN v0.9.0 在 13.60 的完整配方（2026-10-17 实测）

### 7.1.1 有一个**必须先处理的冲突**

OnionHEN 内置 **kstuff-lite 1.11**，而 13.60 跑 fpkg/backport 用的是
**kstuff-fpkg 1.13-dr-testN**（本机 `kstuff-fpkg-1.13-dr-test6.elf`，1,818,680 B）。
两者都会 patch 内核，直接叠加等于**降级 + 重复 patch**，最坏情况是 SMP 镜像挂不上、
游戏点了没反应。

**两种解法，选一种：**

| 解法 | 做法 | 适用 |
|---|---|---|
| **A. 关掉自带 kstuff（推荐）** | `config.ini` 里 `[kstuff] autoload=false` | 主机的 autoload 链里已经有 kstuff-fpkg —— 本机采用此法，实测正常 |
| B. 用自家 kstuff 覆盖内置 | 把主机的 kstuff-fpkg ELF 复制为 `/data/OnionHEN/kstuff.elf`（README 明确：该文件优先级高于内置） | 想让它走自己的启动时序、但仍用新版 kstuff |

> 判定 autoload 是否真的生效：跑起来后看进程表的 `kstuff.elf` **CPU 累计时间没有归零/重启**，
> 且时间戳早于 OnionHEN 的启动时刻，就说明没被替换。

### 7.1.2 安装步骤

```text
1. 校验 ELF（官方发布说明里给了 sha256）
   OnionHEN.elf  4,676,224 B
   sha256 1f1f7c883d5d998be1d95d7d80b718f85180f8156f257661b0f445a7c6b7c212
2. 上传到 /data/OnionHEN/OnionHEN.elf（目录不存在就建）
3. 写 /data/OnionHEN/config.ini（关键项见下）
4. 冷启动后必须经外部 elfldr:9021 发一次（连接后等 1.3 s，见 §4）
5. 等 30–40 s：bootstrapper 会自行展开 26.5 MB 的 onionhen.elf + assets/ + games/ + cheats/
6. 验证：见 7.1.3
```

启动链（日志可对照）：
```
OnionHEN.elf → bootstrapper → onion_elfldr.elf(:9020) → util.elf → kstuff(可跳过) → daemon.elf → Toolbox
```
第一跳**必须**是外部 elfldr 的 9021；起来之后它用自己 9020 的 `onion_elfldr`，
把 9021 只留作恢复路径。

### 7.1.3 成功判据（日志原文，`/data/OnionHEN/OnionHEN.log`）

```
=========== starting OnionHEN (0x1360) ... ===========   <- 0x1360 = 13.60，固件识别正确
[JB] runtime active: PID/vnode monitoring, jailbreak=on  <- 提权成功（hwinfo 就是死在这一步）
Toolbox online for SceShellUI pid=58                     <- 主页右上角出现图标
fps sampler started (skip-hook, 33333 us)                <- FPS 采样（/dev/dce scanout + AgcDriver）
vsync fps sampler started (scanout, 33333 us)
fan maintenance started (rewrite every 2 s)
```
`OnionHEN_crash.log` 应为 **0 字节**。

进程表应出现三个：`onion_daemon.elf` / `onion_util.elf` / `onion_elfldr.elf`。

### 7.1.4 无害告警（13.60 上一定会看到，别当故障）

```
[ShellUI] error: failed to find method "UpdateNavigationState" in class "ReactNavigatorManager"
[ShellUI] error: failed to find method "CaptureScreen" in class "CaptureController"
[sprx-manager] line=0: cannot open manifest: No such file or directory
[Daemon] error: Daemon returned NO ERROR
```
前两条是 13.60 的 ShellUI 类名/方法名变了，对应 hook 挂不上（影响导航状态与截图 hook，不影响
overlay 和 Toolbox 主体）；第三条是没装 sprx 插件；第四条字面就是「没有错误」，是它自己的日志级别 bug。

### 7.1.5 资源占用（本机实测，CFI-1018B）

| 进程 | 常驻内存 | 空闲 CPU（单核占比） |
|---|---|---|
| onion_daemon.elf | 20.84 MB | 1.02 % |
| onion_elfldr.elf | 16.75 MB | 0.01 % |
| onion_util.elf | 14.42 MB | 0.00 % |
| **合计** | **52.0 MB**（≈ 16 GB 的 0.3%） | **≈ 1 %**（8 核整机 ≈ 0.13%） |

对照：`SceShellUI` 887 MB / 35 %、`AgcCompositor.elf` 356 MB。
→ 结论：**常驻成本可忽略**；游戏内 overlay 会额外采样+绘制，量级 1–3 %，未单独实测。

### 7.1.6 overlay 配置项（`/data/OnionHEN/config.ini` 的 `[overlay]`）

```
enabled=true          总开关
edge=top | bottom     贴屏幕哪边（挡视野就改 bottom）
align=left|center|right
show_fps / show_cpu / show_gpu / show_memory / show_fan_duty / show_ip_address  = true|false
font_size=small|medium|large
order=fps,cpu,gpu,memory,ip,fan
```
同样的项目也能在 Toolbox 图形界面里改，改完不用重启。

### 7.1.7 开机自动加载（pldmgr autoload 路线，⚠️ 待实测）

`pldmgr` 的 `/data/pldmgr/autoload.txt` 每行一个 `local/<id>` 或 `repo/<id>@<hash>`，
它启动时按行加载。这与 §5「手工塞进 local/ 点不动」**是两条不同的代码路径**：

```text
/data/pldmgr/payloads/local/onionhen/
    OnionHEN-v0.9.0.elf
    meta.json            # schema 2 / kind local / filename 指向上面那个 elf
/data/pldmgr/autoload.txt  （追加最后一行）
    local/kstuff-fpkg
    local/nanodns
    repo/shadowmountplus@e8cce5d1
    local/onionhen          <- 必须放最后：它依赖 kstuff 已经上过补丁
```

> ⚠️ 本机已按此写好，但**尚未经历一次冷启动验证**。开机后按 7.1.3 的日志判据核对；
> 若没起来，退回「手动用 elfldr 发一次」，并把该行注释掉。

### 7.1.8 卸载（三步，顺序不能反）

```text
1. 撤自启：删 /data/pldmgr/autoload.txt 里的 local/onionhen（或用备份覆盖）
2. 重启主机（让 daemon / util / elfldr 三个进程退出、ShellUI 里的 Toolbox 消失）
3. 删目录：/data/OnionHEN/   （26 MB 主体 + 日志 + assets，重启后无占用才能删干净）
   （可选）/data/pldmgr/payloads/local/onionhen/
```
**不要跳过第 2 步直接删**：日志文件被 daemon 持有，删不干净会留残档。
只删目录不撤 autoload → 下次开机会因为找不到 ELF 而报错（通常只是跳过，但没必要留这个坑）。

---

## 8. 一句话判据

```
面板说"已加载" → 先查三条：专属端口 / klog 进程表 / 该工具日志的 mtime
  三条全否 → 它压根没起来（UI 骗人）
klog 出现 SIGILL + payload.elf + privileged instruction fault
  → 取 rbx 当基址、rip 当偏移，确认是 ud2（= 载荷初始化放弃）
  → 但别据此判"无解"：换新 SDK（≥0.42）构建 / 明确支持 13.60 的同类载荷再试一次
要温度且不想折腾 → ps5-exporter，elfldr 9021 发送，等 1.2 s，读 http://IP:9100/metrics
问「XX ℃ 正常吗」→ 先看风扇 duty：<25 % 说明余量充足，78 ℃ 也正常；
  风扇 >60 % 仍 78 ℃ 才是散热吃力（判读区间见 §6.1.2）
要电视上实时看 FPS+温度 → OnionHEN v0.9.0，**config.ini 里 [kstuff] autoload=false**（§7.1.1），
  elfldr 9021 发一次，日志出现 "starting OnionHEN (0x1360)" + "Toolbox online" 即成
```
