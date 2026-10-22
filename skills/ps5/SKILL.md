---
name: ps5
description: PS5 游戏文件转换、U 盘部署与运行期排障工具集。用于 FPKG(.pkg) 转 exFAT/ffpkg/ffpfs/ffpfsc 镜像、镜像反向转回 pkg、游戏文件夹与压缩包解包、镜像结构检查与校验、ShadowMountPlus (SMP) 挂载前的合规检查；也用于排查「镜像/文件夹挂得上、图标也出得来，但游戏启动后崩溃或卡死」——包括读 SMP debug.log 区分 hang 与 crash、通过 FTP 直连主机取日志与读沙箱、Unity/Addressables 资源加载检查、boot.config 显示请求、fakelib 取舍。还用于实测 U 盘/接口吞吐（PS5 前置 USB-A 是 USB 2.0 口，约 37 MB/s；背面 10Gbps 口可到 111 MB/s 以上）判断「游戏加载慢是不是插错口」，以及判断自制载荷（etaHEN / hwinfo / 温度监控）为何一启动就 SIGILL（13.60 官方 etaHEN 不可用，但 ps5-exporter / OnionHEN 已实测能跑）、判读游戏内 CPU/SoC 温度与风扇转速是否正常（如 78 ℃ 算不算过热、要不要清灰）。当用户提到 PS5、FPKG、pkg 转 exfat、外置硬盘/U 盘玩游戏、ShadowMountPlus、转 ffpkg、fakelib/降级补丁、游戏转镜像、CE-108255-1/CE-108264-1、卡在 logo/黑屏无声音、etaHEN、hwinfo、CPU 温度/过热/清灰、debug.log、U 盘速度/插哪个口、NAS/共享游戏库按中文名整理、M.2 扩容选型、主机 IP 变了连不上 等场景时使用。也用于判断某个工具是否支持 .pkg 输入，以及识别 PS4 pkg(7F434E54) 与 PS5 pkg(7F464948) 的区别。
agent_created: true
---

# PS5 游戏文件转换、部署与运行期排障

## 本 skill 有两条独立的路，别混用

| 你遇到的 | 走哪条 | 看哪里 |
|---|---|---|
| 转不动 / 转出来是空壳 / SMP 认不到 / 一启动就报错 | **转换与部署** | 本文档（下面各节） |
| 挂得上、图标也有、**能启动但崩了或卡死** | **运行期诊断** | `references/runtime-diagnosis.md`（§1 先分清 hang 还是 crash） |
| 手里的 pkg 其实是 **PS4 包**（`CUSA`…） | **另一条完全不同的路** | `references/ps4-games-on-ps5.md`（走 PS4Mount，**不是** SMP） |
| 想跑温度/风扇/FPS 监控、装了 etaHEN 或 hwinfo，**一启动就崩或完全没效果**；**就想在 13.60 上看温度**；或**看到某个温度数字不确定正不正常** | **越狱环境本身的问题** | `references/env-1360-jailbreak.md`（先判它到底起没起；§6 是已实测可用的温度方案；§6.1 是读数判读） |

> ⚠️ **动手前先花 5 秒判平台**：`python -c "print(open(r'<x>.pkg','rb').read(4).hex(' '))"`
> → `7f 46 49 48` = **PS5**（本文档适用）；**`7f 43 4e 54` = PS4**（本文档的全部流程都不适用）。
> PS4 包：`ps5-dump-forge` 会直接报 `not a PS5 package: this is a PS4 package (\x7FCNT at offset 0)`；
> SMP 也挂不上（它只认 PS5 的 `sce_sys/param.json`，PS4 是 `param.sfo`）。
> **PS4 游戏必须由主机的 PS4 模拟器从 pkg 装载** —— 走 `references/ps4-games-on-ps5.md`
> （PS4Mount + exFAT U 盘 + 把 pkg 放 **U 盘根目录**）。

> ⚠️ **最重要的认知边界**：本文档顶部那条「✅ 已验证可用的配方」（FSELF 魔数 + 删 7 个
> 安装流程文件）是在**老引擎包**上验证的，**对 Unity 6000 等新引擎包实测无效**。
> 两者的病因完全不同 —— 详细对照见 `references/runtime-diagnosis.md` §9。
> 遇到新引擎游戏卡死时，**不要再拿"删文件"的思路原地打转**。

> ★ **新引擎游戏卡死/极慢，先别急着改包**：拿一个**同机能跑的游戏**（MONOPOLY）跑一遍
> —— 它也慢了就说明是主机环境问题。环境没问题时，当前优先级最高的方向是
> **资源读取加速层 `libSceAmpr` 版本**（§15）和 **`fakelib` 三方对比**（§14）。
> ⚠️ 注意：**「换正品 `libSceAgc` + 补 `libScePsml`」这条路已实测走不通**（vJ 无效，
> 且已用沙箱实证改动确实生效）—— 可以做对比诊断，但别把它当解法。

## ⚠️ 先读这条：FPKG 转出来的镜像，默认**起不来**

判断顺序永远是：**先看有没有「文件夹形态」的完整发布版 → 有就直接转它；只有 pkg 时才转 pkg，并预期可能失败。**

原因是 `.pkg` 里的应用是给**安装流程**准备的，而侧载（folder / exfat / ffpkg）需要另一套东西：

| 项目 | FPKG 内（安装用） | 侧载镜像 / 文件夹 |
|---|---|---|
| `eboot.bin`、`sce_module/*.prx`、`Media/**/*.prx`、`sce_sys/about/right.sprx` | 魔数 `54 14 F5 EE`（PS5 **正品签名** SELF） | 魔数 `4F 15 3D 1D`（**FSELF 伪签名**） |
| `sce_sys/nptitle.dat`、`uds/npbind.dat`、`trophy2/npbind.dat` | **没有**，由安装流程生成 | 侧载发布版会带 |
| `sce_sys/license.dat` / `license.info` / `playgo-*.dat` | 只在 pkg 的**元数据区** | 侧载镜像里**不应存在** —— 这些是零售安装流程的产物，留着会让运行时授权校验失败。**实测去掉即修复** |
| `ampr_emu.index` + `fakelib/libSceAmpr.sprx` | 没有 | 「APR Emu」标题会带 —— `drakmor/ampr_emu` 的路径解析索引（`AMPRIDX3` 头，收录 `/app0/...` 路径 + FNV-1a 哈希表） |

**实测证据**（PPSA17419 MONOPOLY，同标题同版本的两份来源）：

- FPKG 解出的 `eboot.bin` 与完整发布版的 `eboot.bin` **大小完全相同（34,136,733 B），逐字节比对只有开头 4 个字节不同** —— 就是那个魔数。
- 完整发布版把应用里**全部 17 个 SELF**（eboot + 6 个 `sce_module/*.prx` + 9 个 `Media/**/*.prx` + `right.sprx`）都改成了 `4F 15 3D 1D`；FPKG 解出的全是 `54 14 F5 EE`。
- 完整发布版还额外带 `ampr_emu.index`、`fakelib/libSceAmpr.sprx` 和上表那些 `sce_sys/*.dat` —— **`--to folder` 从 pkg 里导不出来**。

**症状**：镜像能被 SMP 正常挂载、图标也出得来，但一启动就报 `CE-108264-1`／`CE-108255-1`
（官方口径「应用程序发生错误」）。

**已由「黄金样本」证实**：用户机上完美运行的 `PPSA14708.exfat`（Commandos: Origins，30.7 GB）
里，应用自身的 15 个模块**全部是 `4F 15 3D 1D`**，而 `fakelib/` 里那 3 个库保持 `54 14 F5 EE`。
与「从 pkg 转出来的镜像」正好相反。详见「4.5 对比诊断法」。

**一条命令判定**（看任意一个 SELF 的前 4 字节）：

```bash
python -c "print(open(r'<游戏目录>\eboot.bin','rb').read(4).hex(' '))"
# 54 14 f5 ee = 正品签名（安装用，侧载大概率报错）
# 4f 15 3d 1d = FSELF（侧载就绪）
```

## ✅ 已验证可用的配方（照这个做，不要再自己发明）

> **⚡ 适用范围（2026-10-16 实测限定，务必先读）**
> 本配方**只在老引擎包上验证过**（PPSA17419 MONOPOLY，Unity 5.x 传统管线、无 Addressables）。
> 在 **Unity 6000.0.52f1 + Addressables + `ps5nggc` 新 NGG 渲染器**的包上
> （PPSA29802 PvZ Replanted 01.510.000）实测**完全无效**：删与不删那 7 个文件，
> SMP 日志表现**一模一样**（`started` → 60 秒无错误 → 静默挂起）。
>
> **先判断包属于哪一类**：`Media/StreamingAssets/aa/catalog.bin` 存在 = Addressables = 新引擎
> → 直接去看 `references/runtime-diagnosis.md`，别在这条配方上耗时间。

2026-10-16 实战 A/B 测试结论，`PPSA17419` MONOPOLY 在固件 13.60 + SMP 上**成功运行**：

> **源用「文件夹形态的完整发布版」（含 FSELF 魔数），然后去掉 8 个「安装流程专用」旁挂文件，再转镜像。**

```bash
# ① 确认是「文件夹形态完整发布版」（eboot.bin 前 4 字节 = 4f 15 3d 1d）
python -c "print(open(r'<发布版>\eboot.bin','rb').read(4).hex(' '))"

# ② 复制一份工作副本，删掉这 8 项
python -c "
import os, shutil
src, dst = r'<发布版目录>', r'<工作目录>/PPSAxxxxx'
shutil.copytree(src, dst)
for rel in ['sce_sys/license.dat','sce_sys/license.info',
            'sce_sys/playgo-chunk.dat','sce_sys/playgo-ficm.dat','sce_sys/playgo-hash-table.dat',
            'sce_sys/origin-param.json','sce_sys/target-param.json','2468c.com.txt']:
    p = os.path.join(dst, rel.replace('/', os.sep))
    if os.path.exists(p): os.remove(p); print('drop', rel)
"
# 注：发布站点的水印文件名各不相同（2468c.com.txt / *.url / readme.txt 之类），一并删掉

# ③ 转镜像（保留 fakelib/、ampr_emu.index、libSceAmpr.sprx —— 这三样必须留）
"$PY" "$SK" convert "<工作目录>/PPSAxxxxx" --to exfat -o "<输出>.exfat" --full-verify
```

**必须保留**：`fakelib/`（含 `libSceAmpr.sprx` 等）、`ampr_emu.index`、
`sce_sys/` 里的 `nptitle.dat` / `npbind.dat` / `keystone` / 图标等。

> ⚠️ **"必须保留 fakelib" ≠ "fakelib 内容没问题"**。实测有发布包的 `fakelib/libSceAgc.sprx`
> 是**自制伪签名**、且**缺 `libScePsml`** —— 这类包能启动但渲染极慢。**保留目录的同时，
> 用它和一个同机能跑的包做三方对比**（`references/runtime-diagnosis.md` §14）。
> 另外 `fakelib/` 里的**正品签名 `54 14 f5 ee` 是正常的**（运行时挂载不看它），
> 只有**应用自身**的模块才需要是 FSELF。

**必须去掉的 7 个「零售安装流程专用」文件**（侧载时反而会让系统把它当成受 DRM 保护的
**已安装**标题，运行时授权校验失败 → `CE-108255-1` / `CE-108264-1`）：

| 去掉的文件 | 原因 |
|---|---|
| `sce_sys/license.dat`、`sce_sys/license.info` | 零售安装时由 PSN 授权流程写入的凭证；侧载存在它们会让运行时的授权路径走错 |
| `sce_sys/playgo-chunk.dat`、`playgo-ficm.dat`、`playgo-hash-table.dat` | PlayGo 分段下载元数据，只服务安装流程（`playgo-scenario.json` 是另一回事，可留） |
| `sce_sys/origin-param.json`、`target-param.json` | 「基础版 + 升级包」合并流程的残留 |

**可以留但不影响**：发布站水印（`2468c.com.txt`、`更多资源请访问….url`）。
实测证据：用户机上**能正常跑的文件夹游戏** `E:\PPSA25286-app` 里就有这两个水印，
而它**没有**上面那 7 个文件。所以水印不是病因，删不删随意。

**实测对照（同一份发布版，只改这 7 项）**

| | 文件数 | 结果 |
|---|---|---|
| 发布版**原样**转出的 `full.exfat` / `full.ffpkg` | 250 | ❌ `CE-108255-1` |
| **去掉这些文件**后转出的 `clean.exfat` | 242 | ✅ **正常运行** |

→ 这条是本 skill 里**唯一被实机验证过**的修复手段。其他所有调整（换 ffpkg、删 fakelib、
换格式）在本次测试里**都没有解决问题**。

**第二个已确认的复现案例（PPSA29802 / Plants vs. Zombies: Replanted 01.510.000）**：
文件夹发布版里 `license.dat`、`license.info`、`playgo-chunk.dat`、`playgo-ficm.dat`、
`playgo-hash-table.dat`、`origin-param.json`、`target-param.json` **7/7 齐全** —— 同一病因。
按上面的配方清理后重打包，156 文件全量 blake3 校验通过。

**另一种成功形态**：如果来源本身就提供**成品外置镜像**（`.exfat` / `.ffpkg`，不是你自己转的），
直接用它最省事 —— 发布者已做过完整转换。用 `probe_exfat.py` 对一下就能确认形态是否合理。

## 核心原则

**源优先于工具**：能用「文件夹形态的完整发布版」就别去转 pkg（理由见上一节）。

**只有一个工具可靠：`quer3q/ps5-dump-forge`**。它是 Rust 写的跨平台 CLI，能直接读 PS5 原生
FIH 容器 / Kraken 压缩 / plaintext(PPRPLAIN-NOAUTH) 外置 PFS，一条命令完成
`pkg → exfat / ffpkg / folder / pkg` 的双向转换。

本机上其他 PS5 工具都是纯 GUI 或能力不全，**遇到 `.pkg` 输入时不要用它们**（详见
`references/toolchain.md`）。优先用 `scripts/forge.py` 封装，它负责自动获取工具、
套用安全默认值、并在转换后做独立几何校验。

```bash
PY="C:<USER_HOME>/.workbuddy/binaries/python/versions/3.13.12/python.exe"
SK="C:<USER_HOME>/.workbuddy/skills/ps5/scripts/forge.py"

"$PY" "$SK" inspect "<源文件>"          # 第一步永远是 inspect
"$PY" "$SK" convert "<源文件>" --to exfat -o "<输出路径>" --full-verify
"$PY" "$SK" verify  "<输出镜像>"         # 独立校验，不依赖工具自身
```

`forge.py` 首次调用会自动把 CLI 版（约 8 MB）下载到 `~/.workbuddy/tools/ps5-dump-forge/`，
之后复用。也可以直接调用工具本身：

```bash
FORGE="$HOME/.workbuddy/tools/ps5-dump-forge/ps5-dump-forge-0.1.1-windows-x86-64/ps5-dump-forge.exe"
"$FORGE" inspect "<源文件>"
"$FORGE" convert "<源文件>" --to ffpkg -o "<输出路径>" --full-verify
```

## 触发场景

- 「把这个 pkg 转成 exfat / ffpkg 镜像」「游戏拷到 U 盘玩」「做外置镜像」
- 「转出来的镜像能挂载、图标也有，但一启动就报 CE-108264-1 / CE-108255-1 / 应用错误」
  → 直接照顶部「✅ 已验证可用的配方」做
- 「完整发布版转出来也报错」→ 发布版里残留了安装流程专用旁挂文件，按配方删掉再转
- 「**文件夹格式**的游戏起不来 / 主界面看不到 / 报 missing param.json」
  → 见「5. 部署」的 ②③：多半是多套了一层目录，或残留了补丁解压出的半成品
- 「同一个游戏既有文件夹版又有 pkg，该用哪个」→ 用文件夹版
- 「这个 pkg 转出来只有参数文件/图标，没有游戏本体」→ 典型 GUI 工具中断，见故障排查
- 「镜像挂不上 / ShadowMountPlus 认不到」→ 查几何与文件名长度
- 「转回 pkg」「解包成文件夹」「镜像校验」
- 「游戏能进、logo 也出了，然后**卡死/黑屏无声音**」→ 走「运行期诊断」，
  先取 `/data/shadowmount/debug.log` 用 `scripts/smp_log.py` 分清 hang 还是 crash
- 「游戏**一直在慢慢加载**、进度条挪得极慢、最后停住」→ 先判"是爬还是死"：
  看进程存活时长（活了十几分钟 = 在爬）+ 看沙箱有没有写入痕迹；再查 `libSceAmpr`（§15）
- 「同机能跑的游戏没事，就这个跑不动」→ **先反过来验一次**：再跑一遍那个能跑的游戏
  （最近也慢了？那就是环境问题）。确认环境无事后，用 **fakelib 三方对比法**（§14）
  + 查 **`libSceAmpr` 版本**（§15）
- 「改完文件跑起来还是一样」→ **别急着记"无效"**：先去沙箱比对
  `<沙箱>/common/lib/<库>` 与 `<镜像>/fakelib/<库>`，证明改动**真的生效过**（§3）
- 「帮我连一下 PS5 看日志 / 看主机上装了什么 / 传个镜像上去」→ 用 `scripts/ps5ftp.py`
  （记得 Git Bash 里先 `export MSYS_NO_PATHCONV=1`）
- 「帮我把一个目录的 pkg 整合成一个 exFAT 镜像」→ **先查魔数**。PS5 包照本文档转；
  **PS4 包没有 pkg→exfat 的工具**，只能把 pkg 原样放进整盘 exFAT 镜像
  （`scripts/mkexfat.py`）交给 PS4Mount —— 见 `references/ps4-games-on-ps5.md`
- 「PS4 游戏（CUSA…）怎么在 PS5 上跑 / 放进去 SMP 不认 / 挂不上」→
  `references/ps4-games-on-ps5.md`（PS4Mount 的 U 盘目录约定、环境要求、固件参照表）
- 「PS4 游戏（PS4Mount 装的）点开停在主画面没反应 / 昨天能跑今天不行」→
  九成是 param.sfo 版本不匹配（0x80a4003c 无限重试），不是游戏坏了；
  升级 PS4Mount 0.6.0 + 面板 API 移除重加即修 —— 见 `ps4-games-on-ps5.md` §6
- 「游戏加载特别慢 / 贴图糊 / 是不是 U 盘插错口了 / 换了个 USB 口还能不能玩」→
  先实测吞吐：`scripts/usb_speed.py`。~37 MB/s = 插在前置 2.0 口（换背面），
  ~111 MB/s = 正常（千兆网封顶）。**换口不影响能否运行**，但换完要重启 PS4Mount
  重新扫描 —— 见 `ps4-games-on-ps5.md` §5
- 「NAS / 路由器共享里的游戏目录太乱，帮我按中文游戏名整理」「共享里的游戏搬个位置」
  → 同一共享内用 `os.rename`（服务端改名，几十 GB 也秒完）；中文名**读 `param.json`
  的 `titleName`**，不要靠目录名猜 —— 见 §5.5
- 「PS5 上的网页打不开 / FTP 连不上 / 端口全不通，但主机明明开着」→
  先怀疑 **DHCP 把 IP 换了**（本机实测 .175 → .177）。用端口指纹（2121 / 8770 / 8888）
  扫网段定位，再在路由器里做静态 DHCP 绑定 —— 见「故障排查」对应行
- 「装了 etaHEN / hwinfo / 温度监控之类，一启动就崩；或者面板说已加载但一点效果都没有」→
  **先按三条判它到底起没起**（专属端口 / klog 进程表 / 该工具日志 mtime），
  SIGILL `privileged instruction fault` = 该载荷初始化放弃（老 SDK 不认识固件，或提权被拒），
  **不等于环境没能力** —— 换新构建的同类载荷。13.60 上已实测可用的是 `ps5-exporter`
  （elfldr 发送 → `:9100/metrics`，温度/风扇齐全）—— 见 `references/env-1360-jailbreak.md`
- 「想在游戏画面里看 FPS / 温度 overlay」「OnionHEN 怎么装 / 怎么开机自启 / 怎么卸载 /
  占多少资源」→ `references/env-1360-jailbreak.md` §7.1（必须先关它自带 kstuff 的 autoload）
- 「跑某游戏 CPU 78 ℃ 正常吗 / 要不要清灰 / 温度多高算过热」→ **别只看绝对温度**，
  拉一次 exporter 把温度和风扇 duty 一起看：风扇 <25 % 时 78 ℃ 属正常高位（实测 3A 峰值即如此），
  >60 % 才 78 ℃ 才是散热吃力。区间与判据见 `references/env-1360-jailbreak.md` §6.1

## 标准流程

### 1. 先 inspect，不要直接转

任何转换前都先跑 `inspect`。它会给出标题、标题 ID、版本、固件要求、文件数、**image mode**
和 `findings`。重点看两项：

- **image mode**：`plaintext (PPRPLAIN-NOAUTH)` 表示不需要 passcode，可以直接转。
  若显示需要密钥，必须用 `--password-stdin` 或 `FORGE_ARCHIVE_PASSWORD` 环境变量提供
  （密钥永远不要作为命令行参数传入）。
- **findings: none**：没有异常才继续；有 findings 时先读它说了什么再决定。

### 2. 确认输出格式

| `--to` | 产物 | 用途 |
|---|---|---|
| `exfat` | `.exfat` | 通用外置镜像，SMP 可挂载，可读写 |
| `ffpkg` | `.ffpkg` | **ShadowMountPlus 官方推荐格式**，优先选它 |
| `ffpfs` | `.ffpfs` | PFS 镜像 |
| `ffpfsc` | `.ffpfsc` | 压缩 PFS 容器，**只读挂载**，体积最小 |
| `folder` | 目录 | 解包出文件树（相当于"提取"） |
| `pkg` | `.pkg` | 逆向生成 debug FPKG（app 中显示为 .fpkg） |
| `lz4` | 目录 | LZ4 打包的 AMPR 资源包 |

用户只说「转成镜像」时**先确认目标加载器**。**默认给 `ffpkg`**（SMP 的 UFS 快路径）；
用户反馈「ffpkg 起不来」时再换 `exfat`，反之亦然 —— 两者是互补的备选关系，不是优劣关系。

社区格式基准（2026-10 快照，`onejailbreak.com` 的格式横评 + SMP 仓库说明）：

| 格式 | 定位 | 适用 |
|---|---|---|
| `folder` | 读取最快，可单文件替换 | **内置 / M.2 SSD**、空间充裕 |
| `ffpkg` | 单文件、**推荐镜像**（UFS），运行期不需额外工具 | 默认单文件方案 |
| `exfat` | 兼容格式，**专给「以 UFS 形态跑不起来」的游戏** | 某些标题只认外置式布局 |
| `ffpfsc` | 仍标注实验性，约省一半体积（150–200 MB/s） | 大库、U 盘、空间优先；重流式加载会卡顿 |
| `pkg` | 零售式安装，Kraken 体积 | **公开支持止于固件 11.60**，且只能装内置 |

补充：**12.00–13.60 区间只能走 folder 与镜像挂载**（FPKG 安装待 Kstuff Next Gen）；
镜像挂载本身有「可能导致关机异常或数据损坏」的已知警告，低固件上更容易触发。

### 3. 转换

大文件耗时长（2.5 GB 的 pkg 约数十秒到几分钟），**用后台任务跑**，不要在前台阻塞。
进度以 JSON lines 打印在 stdout。

- 加 `--full-verify` 做**全量**逐字节校验（默认只做结构校验 + 小文件全量 + 其余随机抽样）。
  交付给用户时建议带上。
- **不要**随手加 `--remove-backport`：它会去掉 fakelib 的降级库。用户需要在低版本固件上运行时
  必须保留降级补丁（默认即保留）。
- `-o` 省略时，工具会在源文件旁按标题 ID 自动命名。

### 4. 校验（两种方式，至少做一种）

- **工具自校验**：`--full-verify`，日志会报告每个文件的 blake3 比对结果。
- **独立校验**：`forge.py verify <镜像>` 直接解析 exFAT 引导扇区与根目录，不依赖工具自身。
  检查卷标签、扇区/簇几何、根目录是否含 `eboot.bin` / `sce_sys` / `sce_module` / `fakelib`。

两道都过才能交付。

**深度诊断**：`scripts/probe_exfat.py <镜像> [--all]` 会把整个目录树走一遍，输出
**每个可执行文件的 SELF 魔数统计**、侧载层文件清单、`sce_sys` 完整内容。
排查「挂得上但起不来」时用它，不要只看 `inspect`。

### 4.5 对比诊断法（定位启动失败最快的办法）

**手上有一个已知能正常跑的镜像时，直接并排比，比任何推理都可靠**：

```bash
"$PY" "$SK_DIR/probe_exfat.py" "<已知能跑的镜像>" > /tmp/good.txt
"$PY" "$SK_DIR/probe_exfat.py" "<我做出来的镜像>"  > /tmp/bad.txt
# 比两项：① 可执行文件 SELF 魔数分布  ② 侧载层关键文件清单
```

实测参照（2026-10，用户机上完美运行的 `PPSA14708.exfat` / Commandos: Origins，30.7 GB）：

| 项目 | 能跑的样本 | 我们的失败样本（从 pkg 转） |
|---|---|---|
| 应用自身模块（eboot + prx + sce_module + right.sprx） | **全部 `4F 15 3D 1D` FSELF**（15 个） | 全部 `54 14 F5 EE` 正品签名 |
| `fakelib/libSceAgc*.sprx`、`libScePsml.sprx` | `54 14 F5 EE`（**故意没改**，运行时挂载不看它） | 同 |
| `sce_sys/` | `nptitle.dat`、`disc_info.dat`、`uds/npbind.dat`、`trophy2/npbind.dat`、`keystone`、`pfs-version.dat`、图标 | 缺 nptitle / npbind / disc_info |
| `fakelib/` 里的授权模拟库 | 6 个：3 个正品 + `libSceAppContent` / `libSceGameUpdate` /**`libSceNpEntitlementAccess`**（FSELF） | 无 |
| 卷标签 | `14708Comman`（**不是标题 ID**，11 字符） | `PPSA17419` |

三条重要结论：

1. **`sce_sys/license.dat`、`license.info`、`playgo-*.dat` 不但不是必需的，而且有害** ——
   完美运行的样本里没有它们；后续 A/B 实测确认，**把它们去掉后游戏就跑起来了**
   （见顶部「✅ 已验证可用的配方」）。反过来，**别把「缺 license.dat」当成启动失败的原因**。
2. **`fakelib/` 里那 3 个库保持正品签名是正常的**（两份样本都是），
   所以「fakelib 的 magic 没改」不代表转换不完整。**要改的是应用自身的模块。**
3. **对比诊断时优先看「多什么」而不是「少什么」** —— 本次故障的全部价值都来自
   「我们的镜像比黄金样本**多**了 license / playgo / origin+target-param / ampr」这一个方向。

### 5. 部署（镜像格式 与 文件夹格式 的规则不一样）

**SMP 的扫描根目录**（`/data/shadowmount/config.ini` 里设了 `scanpath=` 则只扫自定义路径）：

```
内置： /data/homebrew/       /data/etaHEN/games/
外置： /mnt/usb0..7/homebrew/  /mnt/ext0..1/homebrew/   /mnt/usb0..7/etaHEN/games/
另可写 /data/shadowmount/manual.lst 手工指定单个路径
```

**① 镜像格式（`.exfat` / `.ffpkg`）**

直接放进上面任一个 `homebrew/` 目录即可（**镜像文件本身就在 homebrew 下，不要再套一层**）。
**文件名主干 ≤ 63 字节**（`.ffpfsc` 为 58），用 `forge.py check-name <名字>` 验证。
**镜像内部**的游戏文件必须位于**镜像根目录**：`/eboot.bin` + `/sce_sys/param.json`。
用 `--to exfat/ffpkg` 从应用目录转出来的镜像天然符合（`forge.py verify` 会确认根目录结构）。

**② 文件夹格式（folder dump）—— 规则最容易踩错**

```
homebrew/
└── PPSAxxxxx-app/          ← 必须直接把「含 eboot.bin 的那个目录」放在 homebrew 下
    ├── eboot.bin
    ├── sce_sys/param.json
    └── ...
```

**❌ 多套一层就会失败**：

```
homebrew/
└── PPSAxxxxx-app/
    └── PPSAxxxxx-app/      ← 多出的这一层 → SMP 报 missing/invalid param.json
        ├── eboot.bin
        └── sce_sys/param.json
```

官方 README 明确写着「**no extra nesting level**」；默认 `scan_depth=1` 只扫**第一层**子目录，
深层要靠 `scan_depth=2` 或 `recursive_scan=1` 才认（会拖慢扫描）。
**所以交付前一定要确认：`<homebrew>/<游戏目录>/eboot.bin` 与 `<homebrew>/<游戏目录>/sce_sys/param.json`
都能直接命中。**

从发布站下载的包**大量存在双层嵌套**（`PPSA29802-app/PPSA29802-app/…`），
拷到 homebrew 时**要压平一层**，别整个原封不动拷过去。

**③ 一个标题只留一个源**：同一 Title ID 有多个来源（文件夹 + 镜像 + 半成品残留）时，
SMP 会报 `duplicate titleId`，症状是「图标能出、一点就崩」且**错误码每次都变**。
放游戏前先清干净。

### 5.5 游戏库放在 NAS / 网络共享上（含「按中文名整理」）

很多人把文件夹格式的游戏先囤在路由器的 SMB 共享里（本机是 `\\iStoreOS\games`，
credentials 由用户提供），用的时候再拷进 PS5。这里有几条实测经验。

**① 同一共享内的移动/改名是服务端 rename —— 不搬数据**

```python
os.rename(r"\\iStoreOS\games\PPSA02424-app",
          r"\\iStoreOS\games\双人成行\PPSA02424-app")   # 40 GB 也是秒完成
```
不要用「复制 + 删除」，几十 GB 会在千兆网里跑几十分钟，还可能中断留下半份。

**② 「按中文游戏名建目录」不要靠目录名猜 —— 读 `param.json`**

```python
p = os.path.join(game_dir, "sce_sys", "param.json")
title = re.search(r'"titleName"\s*:\s*"([^"]+)"', open(p, encoding="utf-8", errors="replace").read()).group(1)
```
实测映射示例（同一份共享里读出）：

| 目录名 | `titleName` | 建议中文名 |
|---|---|---|
| `PPSA02424-app` | It Takes Two | 双人成行 |
| `PPSA25411-app` | Venus Vacation PRISM - DEAD OR ALIVE Xtreme - | 维纳斯璀璨假期 -死或生沙滩排球- |
| `PPSA36458 Mafia Definitive Edition for PS5 01.002.000` | Mafia: Definitivní edice pro PS5® | 四海兄弟 最终版 |

注意 `titleName` 可能是**捷克语/波兰语/俄语**等本地化版本（欧洲发布站常见），
要以中文区官方译名为准，不要机翻。

**③ 加了中文父目录后，拷回 PS5 时必须只取最内层 app 目录**

```
\\iStoreOS\games\双人成行\PPSA02424-app\        ← 只拷这一层
```
整个 `双人成行\` 拷进 `homebrew/` 就是「多套一层」，SMP 直接报 `missing/invalid param.json`（见 §5 ②）。
**NAS 上的中文分类目录只是给人看的，不是给 SMP 看的。**

**④ 顺手检查「多套两层」的伪目录**

有的发布目录本身就套了两层，实测案例：

```
纯粹台球 Pro\纯粹台球 Pro Pure Pool Pro\PPSA28502 01.011.000\PPSA28502-app 01.011.000\eboot.bin
```
判据很简单：**顶层没有 `eboot.bin` / `sce_sys/param.json` 就是套多了**。
交付前压平成 `<中文名>\PPSA28502-app`。

**⑤ 移动完必须校验**（rename 一般不丢数据，但目录名里的空格/特殊字符会引发意外）

```python
n = sum(len(f) for _, _, f in os.walk(gp))          # 与移动前文件数比对
assert os.path.exists(os.path.join(gp, "eboot.bin"))
assert os.path.exists(os.path.join(gp, "sce_sys", "param.json"))
```
实测四份：5731 / 2731 / 5126 / 7080，移动前后一致即通过。

**⑥ 直接用脚本，别每次现写**

```bash
python scripts/organize_nas_games.py "\\\\iStoreOS\\games"            # 默认只报告
python scripts/organize_nas_games.py "\\\\iStoreOS\\games" --apply    # 执行
```
它会：读 `param.json` 的 `titleName` → 按 `--map` 的 JSON 映射建中文目录 → `os.rename` →
移动后比对文件数并复验 app 目录结构。没有映射的游戏只报告不移动（不做机翻），
并对「多套了层级」「内部有多个 app 目录」单独告警。

## ShadowMountPlus 合规要求

转换后必须同时满足：

1. **几何**：512 字节扇区 + 64 KiB 簇（shift 9/7），这是 SMP 的快路径。
   `ps5-dump-forge` 默认即此几何，用 `forge.py verify` 确认。
2. **命名长度**：主干 ≤ 63 字节（`.ffpfsc` ≤ 58），按 UTF-8 字节数而非字符数计算。
3. **卷标签**：为标题 ID（如 `PPSA17419`）。

### `.exfat` 镜像是**裸文件系统**，不是整盘镜像（实测确认）

拿你机器上**唯一完美运行**的样本 `PPSA14708.exfat`（Commandos: Origins，30.7 GB）逐字段核对：

| 字段 | 值 | 含义 |
|---|---|---|
| 偏移 0 的前 3 字节 | `eb 76 90` | 紧跟的就是引导扇区 → **没有 MBR 分区表** |
| `OEM`（偏移 3） | `EXFAT   ` | 裸 exFAT 文件系统 |
| `PartitionOffset`（0x40） | `63` | 非 0 是正常的，**不必改成 0** |
| `VolumeLength`（0x48） | 59971584 扇区 = 28.597 GiB | 文件大小 ≈ 此值 × 512，**没有额外包头** |
| 位移（0x6C/0x6D） | `9` / `7` | 512 B 扇区 / 64 KiB 簇 |
| `NumberOfFats`（0x6E） | `1` | 单 FAT |
| 备份引导区 | 扇区 12 起与主区一致 | 标准 exFAT |

→ **SMP 的 `.exfat` = 分区内容的裸转储**（相当于把一个分区 `dd` 出来），
**不是**带 MBR 的整盘镜像。所以：
- 要交给 SMP 的镜像：**VBR 必须在偏移 0**，游戏文件在**镜像根目录**。
- 要**写到 U 盘**当磁盘用的镜像：才需要 MBR 分区表（整盘镜像）。

同一份 exFAT 卷可以同时导出这两种形态：
抽 [分区起始扇区×512, +分区扇区数×512) 得裸 `.exfat`；VHD 去掉尾部 512 B 得整盘 `.img`。

## 运行期诊断（能启动但崩了/卡死）

**完整版见 `references/runtime-diagnosis.md`。** 这里只放最关键的骨架。

### 第 0 步：区分 hang 与 crash（这一步决定了后面所有方向）

```bash
export MSYS_NO_PATHCONV=1        # Git Bash 里必须加，否则 /data/... 路径会被改写
PY="C:<USER_HOME>/.workbuddy/binaries/python/versions/3.13.12/python.exe"
"$PY" scripts/ps5ftp.py get /data/shadowmount/debug.log
"$PY" scripts/smp_log.py debug.log --title PPSAxxxxx
```

| 日志组合 | 判读 | 病因方向 |
|---|---|---|
| `[GAME] started` → 60 秒内 `[MDBG] game error monitoring expired`，**无任何 error** | **静默挂起 (hang)** | **运行期**：资源加载 / 无限等待 / 渲染 |
| `[GAME] started` → 数秒内 `[MDBG] game error: 0xA0020318 (SYSTEM_ABNORMAL_TERMINATION_REQUEST)` | **崩溃 (crash)** | 缺必需库 / 签名 / 挂载层 |
| 只有 `[FAKELIB] directory mounted`、**没有** `game mounted` | 游戏自带 fakelib 未生效 | 见下「fakelib 是必需品」 |

还有一个必须记住的技巧：**用户按 PS 键手动退出**在日志里长这样
（`AppFocus 0x07 → 0x6018 → 0x07` + `game stopped`），**别当成崩溃读**。

### 三条硬结论（都是本次实测，能省掉大量弯路）

1. **`fakelib` 必须存在**，但**它的内容仍可能是病因**。这两件事要分开：
   - 删掉整个 `fakelib/` 后进程 **6 秒即死**（0xA0020318）→ `fakelib_mode=disabled`
     / `fakelib_exclude` 是**死路**。
   - 但这**不证明 fakelib 是干净的**。实测本包 `fakelib/libSceAgc.sprx` 是**自制伪签名**
     图形驱动、且**缺 `libScePsml`**，而两个能跑的包都是**正品 Agc + 带 Psml**。
     → 值得比对，但**别指望换正品就能修好**：实测换成"正品 Agc + 补 Psml"= **无改善**
     （且已用沙箱实证改动真的挂上了）。见下「图形栈三方对比」。
2. **★ 下"某招没用"的结论前，必须先证明那一招真的生效过。** 这是本 skill 最贵的教训：
   当晚做了十几个版本，**从没验证过改的文件是否真的挂进沙箱**，所以每条"无效"都不可靠。
   做法：趁进程活着，比 `/mnt/sandbox/<ID>_000/<随机哈希>/common/lib/<库>` 与
   `<镜像挂载点>/fakelib/<库>`。**注意沙箱里是解密后的裸 ELF，体积比 PC 上的 SELF 大**
   （326,617 → 366,600；17,741 → 81,484），别因"大小对不上"误判成没生效。
3. **别用几十秒下结论。** 实测游戏光走完两个 logo 就要约 **1 分钟**，首次加载 1.5 GB 资源
   可能要 **5 分钟**。有一次判定发生在启动后 46 秒，那次判定**不成立**。
   更要紧的是：**"静默挂起"必须用进程存活时长来判**（vH 实测存活 13–15 分钟、零错误、
   焦点稳定 → 它是在**慢慢爬**，不是死锁）。
   **加分探针**：看沙箱里游戏有没有留下写入痕迹 —— `temp0`/`download0`/`data` 全空、
   存档目录 `savedata_prospero/<TITLE_ID>` 不存在、沙箱根 mtime 冻结
   → 说明**卡在非常早期的初始化**，不是"资源读到一半"。
4. **FTP 会透明解密 SELF —— 而且是「上传时」就解密。** 实测：17,741 B 的 FSELF 上传后，
   **远端 SIZE 当场变成 81,484 B** 且 magic 变 `7f454c46`（裸 ELF）。
   → 后果：**改游戏内容只能「PC 改原始目录 → 重打包镜像 → 传镜像」**，且**不能用 FTP 部署
   文件夹格式的游戏**，也**不能用它往 `/data/shadowmount/emus/` 塞库**（那条"让 SMP 自动
   替换假库"的捷径是废的）。
   `scripts/ps5ftp.py put` 已默认拒绝这类上传，并在传后自动回传比对。

### 排查清单（按顺序，每步都可证伪）

| 步 | 查什么 | 位置 |
|---|---|---|
| 1 | **★ 必做**：验证改动是否真的生效 —— 比沙箱 `common/lib` 与镜像 `fakelib` | `/mnt/sandbox/PPSAxxxxx_000/<哈希>/common/lib`（对照 `/preinst/common/lib`） |
| 2 | 游戏"跑到哪一步" —— 沙箱有无写入痕迹 / 有无存档 | 沙箱 `temp0`、`download0`、`data`；`/user/home/<uid>/savedata_prospero/<TITLE_ID>` |
| 3 | SMP 有效配置（尤其 `fakelib_rules`、`fakelib_default_mode`） | `/data/shadowmount/config.ini` + 日志 `[CFG]` 行；Web UI `http://127.0.0.1:10101` |
| 4 | **图形栈三方对比**：拿 1–2 个同机能跑的包，逐文件对齐 `fakelib/` 的**文件名差集 + 签名类型 + md5** | 本地 `PPSAxxxxx-app/fakelib/`，方法见下 |
| 5 | **资源读取加速层** `libSceAmpr` 版本（包内 vs 官方最新） | `<包>/fakelib/libSceAmpr.sprx`（老版 255,750 B / 官方 0.4.2.1 为 423,350 B）|
| 6 | Addressables：catalog 有无 http 链接、`m_CatalogRequestsTimeout` 是否为 **0（永不超时）** | `Media/StreamingAssets/aa/{catalog.bin,settings.json}` |
| 7 | 资源包是否被截断 | 每个 `*.bundle` 的 `UnityFS` 头声明尺寸 vs 实际尺寸（偏差须为 0） |
| 8 | 显示请求 | `Media/boot.config` 里**两条** width + `120hz`（见下） |
| 9 | 模块文件名大小写 | exFAT 无所谓；**换内部 UFS 文件夹格式会 RIP 0 崩溃** |

**★★ 最便宜的大杀器：拿一个「同机能跑的游戏」跑一遍。**
在怀疑"是不是这个包的问题"之前，先让主机跑一个已知能跑的游戏（如
`/data/homebrew/PPSA17419_MONOPOLY_clean.exfat`）。
- 依然流畅 → 主机环境没问题，变量锁定在目标包上
- **也变慢了 → 问题在主机/环境，跟游戏包无关，方向整个换**
这一步只要几分钟，却能一次性排掉最大的变量，性价比远高于继续改包。

**图形栈三方对比**：把"跑不动"的包和"同机能跑"的包放在一起比
`fakelib/` 的**文件名差集**与**签名类型**（`54 14 f5 ee`=索尼正品 / `4f 15 3d 1d`=自制替身）。
实测 PvZ Replanted：**自制伪签名 `libSceAgc`（坏）+ 缺 `libScePsml`（两个能跑的都有）**；
而同批次包（`libSceAgcDriver.sprx` md5 逐字节相同）的正品 Agc **可以直接借来替换**。
**但实测"换正品 Agc + 补 Psml"无改善**（图形栈已排除）。
完整方法与结果表见 `references/runtime-diagnosis.md` §14。

**`boot.config` 改一处不够**：`platform-ps5-video-out-width` 和
`platform-ps5-standardmode-video-out-width` **必须一起改**。只改前者时，一旦关掉 120Hz，
游戏会切「标准模式」、宽度仍取自后者 —— 实测这让一次 1080p 测试**完全没生效**，
差点得出错误结论。

### ❌ 已证伪，不要再试

删整个 `fakelib`／`fakelib_mode=disabled`／exfat↔ffpkg 互换／
按 catalog 补齐带 hash 的 bundle 文件名／只改一条 width 的 1080p 测试／
「文件名后缀 == 文件 MD5」做校验／固件门槛／数据截断／
eboot 签名／`ampr_emu.index` 格式／**两条 width 都改的 1080p**／
**关 Addressables 启动查目录**／「向下兼容补丁打错了」／
「SMP 偷偷覆盖了我们改的 fakelib」（cache 与全局 fakelib 都不存在）／
**「焦点被抢导致 CPU 降频」**／**「镜像/IO 走慢路径」**／**「kstuff 挂着掉速」**／
**「`update_emulators=1` 覆盖 fakelib」**（emus 为空 = 等于没开）／
**「网络等待导致卡死」**（把包内 EA 端点改成 `.invalid` 让 DNS 永久失败 → 无改善）／
**「图形栈被阉割：换正品 `libSceAgc` + 补 `libScePsml`」**（vJ 实测无改善，
且已用沙箱实证这两个库**确实挂给了游戏**）／
**「只补 `libScePsml`、保留自制 Agc」**（vK，同一逻辑的对照版）。
逐条实测结果见 `references/runtime-diagnosis.md` §11。
> 注：**「换最新 `libSceAmpr`」这条早期结论要打折扣** —— vC 当时报"无改善"，
> 但**没验证沙箱**，所以不可靠；已用 vN 重做（见 §15）。

> ⚠️ **这一栏里曾经有过一条「NanoDNS 挡联网导致卡死 → 已证伪」—— 那条是错的，已删除。**
> 原因：NanoDNS 的规则只覆盖 `*.playstation.com/.net/.psndl.net`，
> **从没拦过游戏自己的服务器**，等于实验没生效。
> 详见 `references/runtime-diagnosis.md` §12（含完整的「启动期网络等待」排查法）。
> **纪律：下"某招没用"的结论前，先证明那一招真的生效过。**

### ★ 如果卡死前有「逐级变慢」

过场画面一个一个地过、**每个都等很久**，最后永久停在某一屏，常常伴随**没有声音** ——
先做三件**便宜且能一票定性**的事，别急着开改：

1. **先跑一个同机能跑的游戏**（如 `PPSA17419_MONOPOLY_clean.exfat`）。
   它也不对劲 → **问题在主机环境，跟这个包无关**；那就不用再改包了。
2. **网络要用"域名永不解析"来验，别用"拔路由器 WAN 口"。**
   后者 PS5 仍连着路由器，对外连接是**静默超时**而非立刻失败，实验等于没做。
   真管用的是**拔 PS5 网线**，或直接把包内域名改成 `.invalid`。
   *（PvZ 实测：端点改 `.invalid` 后无变化 → 网络已排除。挖端点方法见 §12。）*
3. **看进程存活时长 + 沙箱写入痕迹**：SMP 日志里 `game error monitoring expired`
   （60 秒零错误）**不等于卡死**；要看 `[GAME] started` 之后活了多久。
   实测存活 13–15 分钟 = 在**慢慢爬**。若同时 `temp0`/`download0`/`data` 全空、
   连存档目录都没建 → 说明**卡在非常早期的初始化**。

若三条都不成立 → 剩下优先级最高的方向是**资源读取加速层 `libSceAmpr`**（§15）。

## 故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| 转出的目录只有 param.json / icon0 / playgo / 奖杯，没有游戏本体 | GUI 工具（PKGViewer / PS5PKGTool）在 plaintext(no-auth) 外置 PFS 上中断，只导出了元数据 | 那个目录是**失败空壳**，删掉重做，改用 `ps5-dump-forge` |
| 工具报需要 passcode / 密钥 | 不是 plaintext 镜像 | 用 `--password-stdin` 传入密钥 |
| SMP 认不到镜像 | 文件名过长，或几何不是 512 B / 64 KiB | `check-name` + `verify` 逐项排查 |
| 加 `--remove-backport` 后低版本固件起不来 | 降级库被去掉 | 重新转，不要加该参数 |
| 桌面 `exFAT.Image.Builder.exe` 打不开 .pkg | 它只认 exfat/ffpkg/ffpfs/ffpfsc，**不认 pkg** | 先转成 ffpkg/exfat 再交给它 |
| 不确定 pkg 是 PS4 还是 PS5 | 看文件头 4 字节 magic | `7F 43 4E 54`=PS4(CNT)，`7F 46 49 48`=PS5(FIH) |
| 镜像能挂载、图标也出得来，一启动就报 `CE-108264-1` / `CE-108255-1`；**文件夹格式同样报这个** | 官方口径「**应用程序发生错误**」= 应用已启动后崩了。两个已实测确认的原因：① **镜像是从 pkg 转的** —— SELF 是安装用正品魔数 `54 14 F5 EE` 而非 FSELF `4F 15 3D 1D`；② **发布版里残留了「安装流程专用」旁挂文件**（`sce_sys/license.dat` / `license.info` / `playgo-chunk\|ficm\|hash-table.dat` / `origin-param.json` / `target-param.json`）。**文件夹格式和镜像格式共用同一套内容**，所以同一个病因在两种格式上都会犯 | 换「文件夹形态的完整发布版」并**去掉那 7 项**后重做 —— 见文档开头「✅ 已验证可用的配方」 |
| 文件夹格式游戏**根本不出现在主界面**，或日志报 `missing/invalid param.json` | ① 目录多套了一层（`homebrew/PPSAxxxxx-app/PPSAxxxxx-app/eboot.bin`）；② 拷贝的是「补丁解压出的半成品」，它的 `sce_sys/` 只有 `about/right.sprx`、**没有 `param.json`**；③ 放的位置不在 SMP 扫描根里 | 压平一层，确保 `<homebrew>/<游戏目录>/eboot.bin` 与 `<homebrew>/<游戏目录>/sce_sys/param.json` 直接命中；确认放进了 `homebrew/` |
| 文件夹里同时有「补丁 zip 解压出的散件」和「真正的 app 目录」 | 发布站常把降级补丁单独打一个 zip，解压到顶层就会生成一个 eboot.bin + 残缺 `sce_sys/` 的**假应用** | 那个顶层目录是垃圾，**删掉或移出扫描路径**；只用含完整 `sce_sys/param.json` 的那个 app 目录 |
| 同一个游戏本机既有完整文件夹版、又下了 pkg | 文件夹版是**侧载就绪**的，pkg 是**安装用**的 | **优先用文件夹版**转镜像 |
| 想直接判断两份来源哪个能用 | 看任意 SELF 前 4 字节 | `4f 15 3d 1d` = FSELF（侧载就绪）；`54 14 f5 ee` = 正品签名（安装用） |
| 报 `CE-108262-9`，或点图标完全起不来 | 读取系统软件/应用数据出错；偏挂载层 / kstuff / 版本检查 | 查几何与命名、升级 SMP 与 kstuff、读 `/data/shadowmount/debug.log` |
| 想做 pkg 安装而非镜像 | 需要 kstuff（含 FPKG 支持）+ `a53_ppr_install`(drakmor) + SMP 的 fpkg 支持；**且固件须 ≤ 11.60** | 超过 11.60 只能走镜像（exfat / ffpkg） |
| 把一个目录的 pkg 做成 exFAT 镜像，`ps5-dump-forge` 报 `not a PS5 package: this is a PS4 package (\x7FCNT at offset 0)` | 那是 **PS4 包**（标题 ID 前缀 `CUSA`/`PCAS`…）。换别的 PS5 工具也没用 —— **不存在「PS4 pkg → exFAT」的工具** | 走 PS4Mount：把 pkg **原样**放进 exFAT U 盘**根目录**；要单文件就用 `scripts/mkexfat.py` 做整盘镜像。见 `references/ps4-games-on-ps5.md` |
| PS4 游戏的 exFAT 镜像放进 `/data/homebrew`，SMP 完全不理 | SMP 只扫 **PS5** 游戏（判据 `sce_sys/param.json`）；PS4 是 `sce_sys/param.sfo`，容器格式也不同 | 别用 SMP。用 PS4Mount（U 盘 + `ps4mount.elf` + klogsrv），游戏由主机的 PS4 模拟器装载 |
| 拿到一堆 PS4 pkg（本体 / 更新 / DLC），想「合并成一个」 | PS4 的「本体 + 更新 + DLC」是主机**装载时分层**的，不是文件级 overlay，不能靠合并文件树实现 | 原样保留全部 pkg，让 PS4Mount 去配对（本体 + `patch.pkg` + `addcont/`）；见 `ps4-games-on-ps5.md` §3 |
| PS4Mount 装的 PS4 游戏**停在主画面无反应**（常伴「昨天能跑今天不行」） | 主机启动检查逐字节比对 appmeta 的 param.sfo 与更新包 sfo；0.5.1 注册竞态把版本写成本体 01.00 而补丁 01.15 已暂存 → `0x80a4003c The version is newer for DownloadData[0] than App` 无限重试（日志 `/data/ps4mount/log.txt` 实锤） | 升级 PS4Mount 0.6.0（GitHub releases，核对 sha256）→ 面板 `POST /api/unmount` + `/api/mount` 干净重加。成功的标志：日志无 `(still running)`；0.6.0 不会再打 `rewritten` 行，别误判。见 `ps4-games-on-ps5.md` §6 |
| PS4 游戏的加载**明显慢**、贴图糊、切场景卡 | U 盘插在**前置 USB-A（USB 2.0 口）**。同一块盘实测：前置 37 MB/s，背面 111 MB/s（已顶千兆网天花板），**差 3 倍** | 用 `scripts/usb_speed.py` 实测（必须同时测内置盘做对照，且 offset 要避开缓存）；确认为 35–40 MB/s 就把盘换到**背面 USB-A** |
| 换了个 USB 口 / 重新插拔后，担心游戏还能不能跑 | **不影响**。挂载点是按枚举序号的 `usbN`，单盘恒为 `usb0`；PS4Mount 每次启动都重新扫描注册 | 换完口**重启一次 PS4Mount** 再点游戏。唯一例外：同时插两块以上 USB 存储时序号可能互换，拔到只剩一块再重扫 |
| 自制载荷（温度/风扇/FPS/hwinfo/etaHEN）一启动就崩，klog 报 `SIGILL` + `privileged instruction fault`，线程是 `SceSpZeroConfMain`、进程名 `payload.elf` | 取 `rbx` 当基址、`rip` 当偏移，`0f 0b`(ud2) 紧跟一段 `mov rax,[rip]; mov rcx,[rax+0x28]; mov edi,[rcx]; call rax` = **SDK 运行时的"初始化失败→主动 trap"**。两种成因：① 老 SDK 的启动代码不认识这版固件（进不到 `main()`，日志零输出）② 要 `kernel_get_ucred_attrs` 提权而 `kstuff` 给不了 | **ud2 只证明载荷在放弃，不证明环境没能力**。换一个**明确声明支持 13.60 / 用 SDK ≥v0.42 构建**的同类载荷重试 —— 见 `references/env-1360-jailbreak.md` §3.1 |
| **想在 13.60 上看温度 / 风扇转速**（不想装 etaHEN） | 已实测跑通：`Marice/ps5-exporter` v0.2.0，纯库调用、不吃固件偏移表，作者在 13.60 上验证过 | elfldr 9021 发送（**连接后等 1.2 s 再发**）→ 读 `http://<IP>:9100/metrics`。实测 CPU 44 ℃、17 路 SoC 温度、风扇 18.6%、频率/进程/存储共 31 个指标族。详见 `env-1360-jailbreak.md` §6 |
| **「跑某个游戏 CPU 78 ℃ / 85 ℃，正常吗」** | 单看绝对温度会误判。**要配风扇占空比一起看**：本机风扇最低档 18.55 %，原生 PS5 3A（《羊蹄山之魂》）实测峰值 78 ℃ 而风扇仍 18.55 % = 余量充足、完全正常 | 判读区间：待机 35–50 / 一般 50–70 / 3A 高位 70–82（正常）/ 82–88 留意 / 88+ 降频 / ≈105 强制关机。**风扇 <25 % 时 78 ℃ 无事；>60 % 还 78 ℃ 才是散热吃力（清灰、查摆放）**。⚠️ 别拿 PS4Mount 的 PS4 游戏读数（44–65 ℃）当基线横向比。详见 `env-1360-jailbreak.md` §6.1 |
| **「有没有无用的软件在占内存 / 内置盘怎么越来越满 / 能不能清一下」** | 先分清内存和磁盘：载荷进程合计不到 100 MB，不是瓶颈；堆的是**磁盘与日志**（本机 `ps4mount/log.txt` 两天涨到 13.9 MB，其中 2.6 万行是同一句重复错误） | 用 FTP 盘点：`/data` 各目录体积 + `ps5_autoloader/autoload.txt` + `pldmgr/autoload.txt` 判断谁在链上。**在自启链或 SMP 游戏库里的一个都别删**；删前先本地备份并逐文件比对大小。⚠️ `DELE` 返回 `226` 是成功（ftplib 会误抛异常）。详见 `env-1360-jailbreak.md` §6.2 |
| 想在**电视上**实时看 FPS + 温度（游戏内 overlay） | **OnionHEN v0.9.0 实测可跑**，但它内置 kstuff-lite **1.11**，会与 13.60 的 `kstuff-fpkg 1.13-dr` 重复 patch 内核 | 装到 `/data/OnionHEN/`，`config.ini` 里 **`[kstuff] autoload=false`**（复用现有 kstuff），冷启动后经 elfldr 9021 发一次。成功判据：日志 `starting OnionHEN (0x1360)` + `Toolbox online`。详见 `env-1360-jailbreak.md` §7.1 |
| 面板/工具说「已加载」，但功能完全没有（etaHEN 尤其常见） | UI 不可信。判据三件套：① 专属端口（etaHEN = 1337/9081/9090）② klog 的 `FMEM <name>.elf` 进程表 ③ 该工具自己的日志 mtime | 三条全否 = 压根没起来，去查它为什么崩（大概率是上一条）。**13.60 不兼容 etaHEN 2.5B**，实测端口全关、进程不存在 |
| elfldr 日志出现 `socksrv.c:246:recv: Invalid argument`，载荷没被加载 | elfldr 握手用了 `recv(MSG_PEEK\|MSG_WAITALL)`，本固件返回 `EINVAL`；**连接后立刻发数据**就会踩到 | 连接成功后先等 **1～1.2 秒**再 `sendall()`。别据此判定"加载器不兼容" |
| 把 ELF 手动塞进 `pldmgr/payloads/local/<id>/`（含 meta.json），列表能看到但点启动毫无反应 | pldmgr 只认真实登记过的条目；手工放入的仅能被列出，启动无效（klog 零记录） | 想一键启就走仓库/正式安装流程；手工塞的当存档，用 elfldr 发 |
| U 盘/扫描目录里**同一标题 ID 有多个镜像**（如同时放了带 fakelib 和不带的若干份） | 多个镜像都自称同一 Title ID → 挂载/注册冲突，表现为「图标能出、一点就崩」且**错误码每次都变** | **每个标题只留一个镜像**，其余移出扫描路径，重启 SMP 重新扫描 |
| 症状反复、换了格式/删改了文件都没用 | 先怀疑**源本身**：把发布版的 `eboot.bin` 与 pkg 里的比一次 | 若两者**只差开头 4 字节魔数**（其余逐字节相同），说明该「发布版」只是**同一个 pkg 改魔数重打包**，不是独立来源 → 直接换真正独立的来源，别在原地打转 |
| **游戏能启动、logo 都出了，然后卡死；没有错误码** | SMP 崩溃监视器 60 秒内**一条错误都没报** = 静默挂起，病因在**运行期**（加载/等待/渲染），不在签名或挂载层 | 取 `/data/shadowmount/debug.log` 用 `scripts/smp_log.py` 判读 → 走「运行期诊断」那一节 |
| 启动后几秒就死，日志里 `0xA0020318`，且**没有** `[FAKELIB] game mounted` | **缺必需库** —— 多半是 `fakelib/` 被删了 | `fakelib/` 是必需品：删掉后实测 6 秒即死。放回去 |
| 想改游戏里的某个文件，用 FTP 传了 `.sprx` 上去 | ftpsrv **透明解密 SELF**：传上去的签名文件取回来会变成裸 ELF | **不要用 FTP 传签名二进制**。在 PC 上改原始目录 → 重打包成镜像 → 传镜像（`.exfat` 不受影响） |
| 用 FTP 列目录，结果看到的是**文件系统根目录** | 该服务器的 `MLSD` **忽略路径参数**；Git Bash 还会把 `/data/...` 当本地路径改写掉，导致 LIST 失败后退回 MLSD | Git Bash 里先 `export MSYS_NO_PATHCONV=1`；`scripts/ps5ftp.py` 已修正为优先用 `LIST <path>` |
| PS5 的**所有**服务端口同时不通（连 2121 FTP 都关），ping 也不通，但主机明明开着 | **DHCP 把 IP 换了**（本机实测 `.175` → `.177`，租约到期或主机重启后漂移），不是服务挂了 | 并发扫全网段 **2121 / 8770 / 8888 / 8889** 这组端口指纹（PS5 独有组合），命中地址就是新 IP；再用 `curl http://<新IP>:8888/` 确认返回 200。根治：路由器里按 PS5 的 MAC 做**静态 DHCP 绑定**（iStoreOS：网络 → DHCP/DNS → 静态地址分配） |
| 「内置 667 GB 不够用，想加 M.2 / 该买什么盘」 | PS5 只有**一个**空 M.2 插槽，官方支持 **250 GB – 8 TB**（系统软体 23.02-08.00 起；更早版本限 4 TB） | 硬指标缺一不可：**PCIe 4.0(Gen4) x4 NVMe、M.2 2280、Key M、顺序读 ≥5500 MB/s、含散热结构总厚 ≤11.25 mm（板上 ≤8 / 板下 ≤2.45）**。**买 5.0 盘纯浪费**（槽只有 Gen4，自动降速且更热）；M.2 SATA 不认。首次使用必须在 PS5 内格式化一次（**盘上原有数据会被清空**） |
| 改了 `boot.config` 做 1080p 测试，毫无变化 | 只改了 `platform-ps5-video-out-width`，漏了 **`platform-ps5-standardmode-video-out-width`**（关掉 120Hz 后游戏走标准模式，宽度取自后者） | 两条 width 一起改，并处理 `120hz` 行 |
| 新引擎（Unity 6 / Addressables）游戏卡在 logo | 本 skill 那条「删 7 个文件」的配方**对这类包实测无效**（删与不删表现一致） | 别在原地打转，看 `references/runtime-diagnosis.md` §9 判断适用性 |
| **卡死前"过场一个一个地过、每个都很久"，然后永久停住，常伴随没声音** | ★ 头号嫌疑：**启动期在等境外服务端**（EA 账号 gRPC / Sentry 上报）。用 `Grpc.Net.Client` + 境外域名的游戏，在中国大陆 `connect()` 会被黑洞、永不返回 | ① 先用 `scripts/smp_log.py` 确认是 hang 而非 crash；② 挖包里的地址（§12.3）；③ **让主机真正断外网跑一次**（拔 WAN 口、保留局域网）；④ 仍要固化 → 把地址**等长**换成 `.invalid` 域名重打包（§12.5）|
| 想验证"断网能不能过"，于是配了 NanoDNS 把域名指向 0.0.0.0，结果没变化 | ⚠️ **八成是规则根本没覆盖到目标域名**。NanoDNS 默认那套规则只拦 `*.playstation.com/.net/.psndl.net`（为了屏蔽 PSN），**不拦 EA/Sentry 之类的第三方域名** | 先拉 `/data/nanodns/nanodns.log` 看 rules 列表；确认覆盖了再下结论。或者干脆**物理断外网**，最不容易骗自己 |
| 文件夹格式放**内部 UFS** 分区后崩（RIP 0） | 模块文件名**大小写**不符（实测 `Il2cppUserAssemblies.prx` vs 引用里的 `Il2CppUserAssemblies.prx`）；exFAT 不敏感所以镜像上不暴露 | 打包前核对一次大小写；或继续用镜像格式 |

### 鉴别「发布版」是不是 pkg 重打包（30 秒）

```bash
python -c "
a=open(r'<发布版>\eboot.bin','rb').read()
b=open(r'<pkg解出的>\eboot.bin','rb').read()
print(len(a),len(b), sum(1 for i in range(min(len(a),len(b))) if a[i]!=b[i]))"
```
输出第 3 个数 = **4**（且位置是 `0x0..0x3`）时，就是「同一份 pkg 改魔数」。
技巧：`Media/**/*.prx`、`sce_module/*.prx` 也一起比，结论一样就更确定。
**注意**：不要因为「同构」就断定文件格式有问题 —— 实测能跑的黄金样本，
其 SELF 头字段与我们的**逐字段同构**（只有尺寸字段不同），说明贴魔数就是业界通行做法。
差异只可能在**旁挂文件与配置**上。

## backport（降级）包：fakelib 留不留，取决于主机固件

PC 端下载的包里很大一部分是**已 backport 的**：发布者为了兼容低固件，用 `ps5_elf_sdk_downgrade.py`
之类的工具把 `eboot.bin` 及 prx/sprx 的 **SDK 版本下调**，并在游戏根目录放一个 `fakelib/`
（典型 3 个库：`libSceAgc.sprx`、`libSceAgcDriver.sprx`、`libScePsml.sprx`）。

用 `inspect --json` 判定，四个字段最关键：

| 字段 | 含义 |
|---|---|
| `firmware` / `sdk` | 游戏**本来**要求的固件 / SDK（取自 param.json，如 `9.00`） |
| `backport` | 非空即为降级包，列出 `fakelib/*.sprx` |
| `backport_firmware` | **该包被降级到的目标固件**（如 `4.00`）—— 决定 fakelib 取舍的核心项 |
| `backport_blocked` | `--remove-backport` 被拒的原因，通常直接写明 eboot 与 param 的 SDK 冲突 |

### 决策：**默认原样保留 `fakelib/`，不要主动删**

早期判断曾认为「主机固件 ≥ 游戏要求时应删掉 fakelib」，**实测已否定**：
在固件 13.60 的主机上删掉 fakelib 重新打包，报错依旧（`CE-108264-1`），
而发布版本身是带 fakelib 的。真正的差异在顶部那节讲的 SELF 魔数与缺失的侧载层文件。

| 情况 | 怎么做 |
|---|---|
| 手上是**文件夹形态的完整发布版** | 按顶部「✅ 已验证可用的配方」：保留 `fakelib/`、`ampr_emu.index`、`libSceAmpr.sprx`，**去掉那 8 个安装流程专用旁挂文件**后转镜像 |
| 手上只有 pkg，且必须用它 | 先看 eboot 魔数：`54 14 F5 EE` = 安装用格式，侧载大概率报 `CE-108264-1`；能用别的来源就别用 |
| 确实要试去 fakelib（作为对照实验） | 已知**无效**（实测照样崩）。真想删就只在保留其余一切的前提下做，别期待有用 |

**降级不可逆**：eboot 的 SDK 一旦被下调，`--remove-backport` 会被工具拒绝，**原 eboot 拿不回来**
（`backport_blocked` 里会明说 `the original can't be restored`）。
手改 SLDK 字段属高风险操作，**不作为首选**；先换「未降级的原版」或「文件夹形态发布版」。

**症状对照**

- `CE-108264-1` / `CE-108255-1`（官方口径「应用程序发生错误」）= 应用**已启动**后崩了
  → 首要怀疑「SELF 是安装用正品魔数 / 缺侧载层文件」（见文档开头那节）；
  其次才是 fakelib 与主机固件不匹配。
- `CE-108262-9`（读取系统软件/应用数据出错），或点图标完全起不来 → 偏挂载层 / kstuff / 版本检查。
- `CE-10826-1` 不在索尼官方表里，多半是 `CE-108264-1` 或 `CE-108262-9` 少打一位。

**解包与重组**（想改内容再打包时用；`-o` 必须是**尚不存在**的目录，且**父目录必须先存在**）：

```bash
"$FORGE" convert "<镜像>" --to folder -o "<父目录>/<新目录名>"
"$FORGE" convert "<新目录名>" --to exfat -o "<输出>.exfat" --full-verify
"$FORGE" convert "<新目录名>" --to ffpkg -o "<输出>.ffpkg" --full-verify
```

也可临时在 `/data/shadowmount/config.ini` 里设 `backport_fakelib=0` 做零成本验证
（可逆，但会影响所有游戏）。

### 两条社区共识（有据可查）

- **BackPork 官方 README**：sideload 的库「必须来自与目标游戏兼容的固件版本」，
  且补丁版「改动了函数的正常行为」；sideload 越少越好。
- **社区排查经验**：`fake libs are being stripped of dependencies required for higher firmwares`
  —— 降级库在更高固件上会**拿掉**游戏需要的能力。同源建议：**能用未降级版就别用降级版**。

## 参考资料

- `references/toolchain.md` — 本机与社区各工具的能力矩阵、版本、命令行支持情况、坑位清单。
- `references/fpkg-format.md` — FPKG 内部结构（FIH 容器、外置 PFS、config ZIP 区）、
  exFAT 引导扇区字段含义、SMP 挂载规则。手工解析或排查二进制问题时读它。
- `references/runtime-diagnosis.md` — **运行期排障playbook**：SMP 日志判读（hang vs crash）、
  FTP 直连主机、沙箱探察、SMP 配置项、Unity/Addressables 检查点、`boot.config`、
  `ampr_emu` 说明、发布站质量缺陷清单、**已证伪清单**、判定纪律。
- `references/ps4-games-on-ps5.md` — **PS4 游戏（CUSA…）在 PS5 上怎么跑**：平台判据（魔数 +
  标题 ID 前缀）、为什么 `ps5-dump-forge` 与 SMP 都用不上、PS4Mount 的 U 盘目录约定与环境要求、
  固件与 PS4 游戏兼容参照表、**§5 U 盘接口速率与换口影响**（前置 2.0 = 37 MB/s vs 背面
  10Gbps = 111 MB/s；换口不影响运行但需重启 PS4Mount）、整盘 exFAT 镜像的做法、
  **运行期排障 §6**（停在主画面 = 0x80a4003c 版本不匹配；0.5.1→0.6.0 升级流程；
  8770 面板 API；启动顺序纪律）、双点医院 CUSA15884 实测记录。
- `references/env-1360-jailbreak.md` — **越狱环境与「自制载荷跑不起来」**：
  怎么确认主机到底在跑哪些载荷（klog 的 `FMEM` 行 + 端口表）、etaHEN 在 13.60 上
  起不来的三重判据、`SIGILL privileged instruction fault` 崩溃签名与 `ud2` 反查法、
  elfldr 的 `MSG_PEEK`/`EINVAL` 时序坑、pldmgr 手放载荷点不动；
  **§6 已实测可用的温度方案（ps5-exporter）**、
  **§6.1 温度读数判读（实测基线 44 ℃ 空闲 / 78 ℃ 3A 峰值、风扇 18.55 %；判读区间、
  三个误判坑、需要动手的信号）**、
  **§6.2 磁盘盘点与清理（内存 vs 磁盘先分开、`DELE` 返回 226 属成功、正在写的日志怎么安全裁剪、
  /data 体积基线、清理纪律）**、
  **§7.1 OnionHEN v0.9.0 完整配方**（kstuff 冲突规避、安装步骤、成功判据、无害告警清单、
  实测资源占用 52 MB / ≈1% 单核、overlay 配置项、pldmgr autoload 自启、三步卸载）。
- `scripts/usb_speed.py` — 走 FTP 实测 U 盘/内置盘读取吞吐（不需要主机端载荷）：
  `~37 MB/s` = 插在前置 2.0 口，`~111 MB/s` = 顶到千兆上限（U 盘本身更快）。
  必须同时测内置盘做对照，offset 要避开页缓存。
- `scripts/mkexfat.py` — 把一个目录收拾成「整盘 exFAT 镜像」（diskpart 建 fixed VHD →
  格式化成 exFAT → 复制 → 剥掉尾部 512 B footer 得到裸 `.img`）。给**不能转换**的原始文件
  （如 PS4 pkg）用；只依赖 Windows 自带的 diskpart。
- `scripts/forge.py` — 工具获取 + 转换 + 校验封装（仅依赖标准库）。
- `scripts/probe_exfat.py` — exFAT 镜像深度诊断（仅依赖标准库，不依赖 forge）：
  遍历目录树、统计 SELF 魔数、检查侧载层文件。排查启动失败时先用它。
- `scripts/smp_log.py` — 解析 `/data/shadowmount/debug.log`，输出启动时间线并**直接判读
  hang / crash**。排查「能启动但跑不起来」的第一步。
- `scripts/ps5ftp.py` — PS5 (etaHEN ftpsrv) FTP 助手：`ls` / `tree` / `cat` / `get` / `put` / `find`。
  `put` 会拒绝上传签名二进制并自动回传校验。
- `scripts/organize_nas_games.py` — 把 NAS/共享里的游戏目录按**中文游戏名**归类：
  读 `param.json` 的 `titleName`、按 JSON 映射建中文目录、`os.rename`（同卷服务端改名，
  百 GB 秒完成）、移动后比对文件数并复验 app 目录、告警「多套了层级」。默认只报告，
  `--apply` 才动手。见 SKILL §5.5。
- `scripts/find_ps5.py` — 主机换了 IP 时用**端口指纹**（2121/8770/8888/9100）扫网段找回它。
  判据看**组合**：单看 8888 会误报（实测路由器 `<PRIVATE_IP>` 也开着 8888），
  `2121 + 8770` 同时开才基本锁定 PS5。

## 环境注意

- 需要手工解析 pkg / exFAT 镜像时，用托管 Python：
  `C:<USER_HOME>/.workbuddy/binaries/python/versions/3.13.12/python.exe`
- 本机 PowerShell 不回传 stdout、Git Bash 缺 coreutils，脚本一律用 Python 直接读写文件。
- **Git Bash 的 MSYS 路径转换会吃掉以 `/` 开头的参数**（实测 `/mnt/sandbox/...` 被改写成
  `D:/Program Files/.../PortableGit/mnt/sandbox/...`）→ 传远程路径给脚本前先
  `export MSYS_NO_PATHCONV=1`，或改用 heredoc 让路径留在 Python 字符串里不经 shell。
