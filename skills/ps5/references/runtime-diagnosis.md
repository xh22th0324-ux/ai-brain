# 运行期诊断：镜像/文件夹挂得上、但游戏跑不起来

转换与部署规则见 `SKILL.md`；本文只管**东西已经在主机上、走到哪一步坏了**。

> **先记住一条分界线**：`转换部署` 解决的是「装不上/认不到/一启动就崩」；
> `运行期诊断` 解决的是「**能启动、能出画面，然后卡死或崩**」。
> 两者病因完全不同，**不要拿前者的经验去套后者**（2026-10-16 实测踩过这个坑，见 §9）。

---

## 1. 第一件事永远是：拿到 SMP 日志，先分清 hang 还是 crash

```
FTP 取 /data/shadowmount/debug.log        （会滚动，旧的在 debug.log.1）
解析：python scripts/smp_log.py debug.log [--title PPSA29802]
```

日志里最关键的是这几行的**组合**：

| 日志行 | 含义 |
|---|---|
| `Mounting image: <path>` | 挂载开始 |
| `[FAKELIB] game mounted for PPSAxxxxx: <镜像>/fakelib -> /mnt/sandbox/.../common/lib` | **游戏自带 fakelib 已生效**（压在系统真库之上） |
| `[FAKELIB] directory mounted`（**没有** `game mounted`） | 只挂了目录、**游戏自带 fakelib 没挂上** → 游戏可能因缺库直接死 |
| `[GAME] started: PPSAxxxxx pid=N` | 进程起来了 |
| `[MDBG] monitoring game errors: ... for up to 60 seconds` | SMP 崩溃监视器开始盯，**is 60 秒** |
| `[MDBG] game error monitoring expired: ...` | **60 秒内一条错误都没有** |
| `[MDBG] game error: 0xXXXXXXXX (NAME) ` + `thread: eboot.bin` | 真崩了，有错误码 |
| `game stopped ... layers=N` | 进程结束；**layers 变少**说明少挂了一层东西 |

**判读规则（这是本文最有价值的一条）**

- `started` → 60 秒 `game error monitoring expired`，且**没有** error 行 ⇒ **静默挂起（hang）**，不是崩溃。
  病因几乎一定在**运行期**（加载、等待、渲染），而不在签名/挂载/旁挂文件上。
- `started` → 几秒内 `game error: 0xa0020318 (SYSTEM_ABNORMAL_TERMINATION_REQUEST)` ⇒ **进程被杀**，
  通常意味着**缺了必需的库或依赖**（实测：删掉整个 `fakelib/` 后就是这一条，6 秒即死）。
- 你手动按 PS 键退出，日志里会有 `AppFocus 0x07 → 0x6018 → 0x07` + `game stopped` ——
  这是**你自己退的**，不要当崩溃读。

**实测对照（PPSA29802 PvZ，同一台主机）**

| 版本 | 文件数 | 日志表现 | 结论 |
|---|---|---|---|
| 清理版（删了那 7 个安装流程文件） | 156 | `started` → 60s expired，0 错误 | 静默挂起 |
| 原样版（一个文件都没删） | 165 | **完全相同** | 静默挂起 |
| vA（删掉整个 `fakelib/`） | 160 | 6 秒后 `0xa0020318`，无 `[FAKELIB] game mounted` | **崩** |

→ 前两行说明「删那 7 个文件」对**这个包**毫无影响（配方不适用，见 §9）；
→ 第三行说明**fakelib 必须存在**（但"内容"仍可能是病因，详见 §6 与 §14）。

---

## 2. 直连主机（PS5 FTP）——比反复问用户快得多

本机对应用户主机的地址（etaHEN 内置 ftpsrv）：

```
host <PRIVATE_IP>   port 2121   用户名/密码：留空（anonymous）
被动模式；建议用起来就设 40s 超时
```

用 `scripts/ps5ftp.py`（已封装）：

```bash
PY="C:<USER_HOME>/.workbuddy/binaries/python/versions/3.13.12/python.exe"
"$PY" scripts/ps5ftp.py ls   /data/shadowmount
"$PY" scripts/ps5ftp.py tree /data/homebrew 2
"$PY" scripts/ps5ftp.py get  /data/shadowmount/debug.log
"$PY" scripts/ps5ftp.py cat  /data/shadowmount/config.ini
```

**能直接读到的关键位置**

| 路径 | 内容 |
|---|---|
| `/data/shadowmount/config.ini` | SMP 配置（见 §5） |
| `/data/shadowmount/debug.log` | SMP 日志（§1）；`debug.log.1` 是上一份 |
| `/data/homebrew/`、`/data/etaHEN/games/` | SMP 的扫描根，看现在实际装的是哪几个版本 |
| `/mnt/sandbox/PPSAxxxxx_000/` | **游戏沙箱**（进程不退出就一直在）：能看运行时实际挂进去的库 |
| `/mnt/sandbox/PPSAxxxxx_000/hXXXXXXXX/common/lib` | 最终生效的「真假库合并结果」 |
| `/preinst/common/lib` | 系统**真实**库（282 个），用于对照 |
| `/user/savedata`、`/user/temp` | 存档与临时区 |

### ⚠️⚠️ FTP 会**透明解密 SELF** —— 禁止用它上传签名二进制

**2026-10-16 二次实测（这次把行为彻底钉死了，因为结论比之前更严重）**：
拿本地 17,741 B、magic `4f153d1d` 的 `libScePlayGo.sprx` 上传：

```
STOR 之后立刻查远端 SIZE  →  81,484 B      ← 不是 17,741！
回读（RETR）              →  81,484 B，magic 7f454c46（裸 ELF）
```

**关键：SIZE 在上传后当场就变了。** 也就是说**解密发生在上传（写入）时**，
不是"取回时才解密"。主机上存下来的**本身就是裸 ELF**。

> 结论（比之前更强）：
> 1. **`.sprx` / `.prx` / `.self` / `eboot.bin` 绝不能经 FTP 写入主机** —— 写进去就是坏的。
> 2. **连"把官方 `emus/` 目录丢进 `/data/shadowmount/emus/` 让 SMP 自动替换假库"这条捷径也废了**
>    —— 传上去的库是裸 ELF，游戏加载会坏。想换库只能**重打包镜像**。
> 3. **不能用 FTP 部署「文件夹格式」的游戏** —— 里面的 prx/sprx 会被逐个解密。
> 4. 顺带：`.elf`、`.exfat`、`.txt` 等**非签名文件传输前后一致**，可放心传。
> 5. **服务器报的大小不可信**，必须回传（`get`）比对大小 + md5 ——
>    `scripts/ps5ftp.py put` 已内置这一步并默认拒绝签名二进制。

**反过来利用这条**：如果你想知道"某个库在主机上到底是什么形态"，直接 `get` 下来看
magic 即可 —— `7f454c46` = 主机上是裸 ELF（被解密过），`54 14 f5 ee`/`4f 15 3d 1d` = 原样。

---

## 3. 进程还活着的时候，去沙箱里看「到底挂了哪些库」

这是判断 fakelib 是否真的生效、以及系统真库里**有没有**游戏要的库的最快办法：

```bash
"$PY" scripts/ps5ftp.py ls /mnt/sandbox/PPSA29802_000/hXW9k722L9/common/lib
```

### ★★★ 这一节是**强制**的：下"某招没用"的结论前，必须先证明那一招真的生效过

**2026-10-16 的教训**：当晚做了 vA~vJ 十几个版本，**从来没有验证过"改的文件是否真的挂进了沙箱"**，
所以每一个"无效"结论其实都不可靠。直到 vJ 才补上这一步：

```
沙箱 .../common/lib/libSceAgc.sprx   ==   镜像 fakelib/libSceAgc.sprx   （大小+内容都对上）
→ 证明改动确实生效 → 那么"没改善"才是可信的结论
→ 图形栈（自制 Agc / 缺 Psml）这条线才能真正关闭
```

**做法**：改完库以后启动游戏，趁进程活着，用 FTP 对比
「`/mnt/sandbox/<ID>_000/<沙箱哈希>/common/lib/<库>`」与「`<镜像挂载点>/fakelib/<库>`」
的大小（或 md5）。注意沙箱里看到的是**解密后的裸 ELF**，大小会比 PC 上的 SELF 大
（例：326,617 B 的 Agc → 366,600 B；17,741 B 的 PlayGo → 81,484 B），
**不要**因为"大小对不上"就误判成"没生效"。

- 实测该目录有 **286+ 条**：系统真实库 + 游戏自带的假库**覆盖在其上**（同名以假库为准，已实证）
  → **假库覆盖链路是好的**。
- 顺手可以核对「游戏导入的库在不在」：如 `libSceShaderTranscode_minimal.sprx` 在系统与沙箱里
  **都不存在**；但**能正常运行的 MONOPOLY 导入表完全一样** → 说明它不是病因（假库内部自己提供）。
- 沙箱哈希目录（`hXW9k722L9`、`m4mnOxgf1y`）是**每次启动随机生成**的，不同游戏/不同次都不同；
  也因此 `/mnt/sandbox/PPSAxxxxx_000/data` 之类目录**每次都是全新的空目录**。

### 沙箱的"写入痕迹"是判断"跑到哪一步"的免费探针

游戏真的在干活时，会在沙箱里留下文件。**全是空的 = 卡在非常早期**：

| 路径 | 实测（PvZ vJ 跑了十几分钟后） |
|---|---|
| `/mnt/sandbox/PPSAxxxxx_000/temp0` | **空** |
| `/mnt/sandbox/PPSAxxxxx_000/download0` | **空** |
| `/mnt/sandbox/PPSAxxxxx_000/data` | **空** |
| `/user/home/<uid>/savedata_prospero/<TITLE_ID>` | **不存在**（同目录里其它 23 个游戏都有存档）|
| 沙箱根 mtime | 停在启动后约 2 分钟，之后不再变化 |

对照要点：**Unity 游戏启动后应该会写 temp / 存档**。二者都没有、且沙箱时间戳冻结
→ 它**还没进入正常工作状态**，瓶颈在初始化阶段，不在"资源读取到一半"。
（另：`savedata_prospero` 里"别人有、你没有"也是一个很便宜的判据。）

> ⚠️ 别用 `/data/etaHEN/fps.log` 判断运行状态 —— 实测它的 mtime 是 `Oct 07`，
> 里面那 20 行 `fps sampler started` 是**旧数据**；`playtime.bin` 同样陈旧。

---

## 4. Unity / Addressables 游戏的专项检查点

PvZ 这类新引擎包（Unity 6000 + Addressables）有几个独特的坑，都是**静态可查**的：

| 检查点 | 位置 | 说明 |
|---|---|---|
| 资源目录 | `Media/StreamingAssets/aa/catalog.bin` + `catalog.hash` | Addressables 的索引。里面**不该有** `http://` / `https://`（纯本地加载才正常） |
| 超时 | `Media/StreamingAssets/aa/settings.json` → `m_CatalogRequestsTimeout` | **`0` = 永不超时**。资源找不到就永久等下去，症状＝卡死（没有崩溃） |
| 启动联网检查 | 同上 → `m_DisableCatalogUpdateOnStart` | `false` = 启动时去检查远端 catalog。纯离线包可以置 `true` |
| 包完整性 | 逐个 `*.bundle` 解析 `UnityFS` 头 | 头里自带声明尺寸，与实际文件尺寸比对，**偏差为 0 才算没被截断** |
| 名字错位 | catalog 里的 `<base>_<32位hash>.bundle` vs 磁盘上的 `<base>.bundle` | **确实会存在**（见下），但实测**不是**卡死主因，修了也没用 |

**关于那 32 位 hash**：**它不等于文件 MD5**（实测 85 个 bundle 里 71 个对不上），
是**构建期**产生的。**不要**再用「文件名后缀 == 文件 MD5」去做一致性校验，这条思路已证伪。

**catalog 与文件名来自两套打包规则**（PvZ 01.510.000 实测）：catalog 要
`uiatlasfrontend_assets_all_55eff31c…bundle`，磁盘只有 `uiatlasfrontend_assets_all.bundle`；
而**原始 rar 里也是不带 hash 的名字，且 rar 里完全搜不到那些 hash**。
→ 是发布方「base 01.000.000 + 补丁 01.500.000 → 01.510.000」合并时留下的错位。
**已实测：按 catalog 补齐这 9 个 + spine 后（vF），表现毫无改善 → 排除。**

---

## 5. SMP `config.ini` 里真正有用的开关

路径 `/data/shadowmount/config.ini`（**追加，不要覆盖**）。Web UI：`http://127.0.0.1:10101`
（主机本机浏览器），可以直接按游戏切假库模式。

| 键 | 作用 | 注意 |
|---|---|---|
| `fakelib_default_mode` | 全局假库模式（`full` / `emulators` / `disabled`） | 1.7beta5 起支持 |
| `fakelib_mode=PPSAxxxxx:emulators` | **按游戏**单独设模式 | `emulators` = 只挂模拟器库，**去掉 Agc/AgcDriver**；`disabled` = 全不用 |
| `fakelib_exclude=PPSAxxxxx` | 连全局假库一起排除 | 实测**有害无益**，见 §6 |
| `global_fakelib_priority=game` | 游戏自带 fakelib 优先于全局的 | 游戏自带的会盖住 SMP 那份 |
| `update_emulators=1` + `emulators_path=/data/shadowmount/emus` | 自动把模拟器库更新到官方最新 | ⚠️ **全局生效**：往里丢文件会替换**每一个游戏**的 fakelib → 别乱用。目录不存在时该功能**静默空转** |
| `kstuff_no_pause=PPSAxxxxx`、`kstuff_delay` | 让 kstuff 不对该游戏暂停 | 卡在极早期（还没进游戏画面）时可试 |
| `backport_fakelib=0` | 关掉降级库 | 影响所有游戏，仅作临时验证 |

**生效确认**：新日志的 `[CFG]` 行里 `fakelib_rules=N`，`0` = 没有任何按游戏的规则生效。
（换句话说：**只改文件、没加规则时，`fakelib_rules` 一直是 0**，别以为配置生效了。）

---

## 6. fakelib：**必须存在**，但**它的内容**仍然可能是病因

两件事要分开看，混起来会连续误判两个方向。

### 6.1 「删掉 fakelib」= 必死（这条路是死的）

反直觉但已实测两次：

- **删掉整个 `fakelib/`（vA）** → 日志里只剩 `[FAKELIB] directory mounted`、
  **没有** `game mounted`，进程 **6 秒后** `0xa0020318` 死掉。
- 有 fakelib → 能走到公司 logo + POPCAP logo 才卡。

所以：`fakelib_mode=disabled` / `fakelib_exclude` 这条路是**死路**，不要再试。

### 6.2 但「fakelib 里的内容可疑」是**必须查**的（→ §14）

上面那条只证明"不能没有 fakelib"，**不证明"fakelib 是干净的"**。
实测发现本包的 `fakelib` 用了**自制伪签名的图形驱动 `libSceAgc`**、且**缺 `libScePsml`**，
而两个能跑的包无一例外都是正品 Agc + 带 Psml。**这是目前图形/渲染方向最硬的嫌疑。**
排查方法见 **§14 三方对比法**。

顺带三条**别被误导**的常识：

- 游戏自带的假 `libSceAgc.sprx` 如果是**索尼原版 + 定点打补丁**（残留构建路径
  `W:/Build/J03718109/...`），**不能仅凭残留路径判它坏** —— 得看签名类型与文件名差集。
- `fakelib` 里那几个「正品签名 `54 14 F5 EE`」是**正常**的（运行时挂载不看它）；
  只有**应用自身**的模块才需要是 FSELF。
- 官方最新 `libSceAmpr.sprx`（`drakmor/ampr_emu` release `0.4.2.1`）是 **423,350 B**；
  很多发布包里那份只有 **255,750 B**（0.3.6.6 时代）。想升级只能在 PC 上换文件后重打包镜像。
  （实测：**升级 `libSceAmpr` 并未改变静默挂起** —— 见 §11。）

---

## 7. `boot.config`（Unity 的显示请求）——改一处不够

`Media/boot.config` 里有两条**宽度**，**必须一起改**，否则测试无效：

```
platform-ps5-video-out-width=3840
platform-ps5-standardmode-video-out-width=3840     ← 极易漏掉这一条
platform-ps5-video-out-120hz=1                      ← 删掉或置 0
```

**实测教训**：第一版只改了 `video-out-width` —— 可一旦关掉 120Hz，游戏会切到
**「标准模式」**，而标准模式的宽度取自 `standardmode-…` 那一行（仍是 3840）。
所以那次「1080p 测试没效果」是**测试本身没生效**，不是结论。

其余相关行：`platform-ps5-gfx-renderer`、`initialization-flags`。

---

## 8. 大小写陷阱（换格式才会炸）

PvZ 实测：磁盘上是 `Media/Modules/Il2cppUserAssemblies.prx`（小写 c），
游戏里另有引用 `Il2CppUserAssemblies.prx`（**大写 C**）。

- **exFAT 镜像**：大小写不敏感 → 无害。
- **文件夹格式放内部 UFS 分区**：大小写敏感 → 直接 **RIP 0** 崩溃。

SMP 仓库 issue #159 就是这类问题（Unity/IL2CPP 游戏因 `.prx` 文件名大小写与请求不符而挂掉，
且牵涉 fakelib / APR Emu 的路径索引）。**改包名/搬格式前先核对一次大小写。**

---

## 9. ⚠️ 配方适用范围：「删那 7 个安装流程文件」不是万能的

`SKILL.md` 顶部那条**唯一实机验证过**的配方（FSELF 魔数 + 删 7 个安装流程文件）是在
**老引擎包**（PPSA17419 MONOPOLY，Unity 5.x 老管线、无 Addressables）上验证的。

**2026-10-16 实测：对 Unity 6000 新引擎包无效。**

| | MONOPOLY（配方有效） | PvZ Replanted（配方无效） |
|---|---|---|
| 引擎 | Unity 5.x 老管线 | **Unity 6000.0.52f1** + Addressables 2.6.0 |
| 渲染器 | 传统 | **`ps5nggc`（新 NGG 渲染器）** |
| 删/不删那 7 个文件 | 删了才好 | **表现完全一致** |

而且**两种格式（镜像 / 文件夹）共用同一份内容**，所以配方在两种格式上同胜同败 ——
换格式不能"绕过"配方是否适用。

**判断方法**：看 `Media/` 里有没有 `StreamingAssets/aa/catalog.bin`（有 = Addressables = 新引擎），
以及 `boot.config` 里有没有 `platform-ps5-gfx-renderer=ps5nggc`。

---

## 10. 发布站质量缺陷清单（2468c 系，实测）

同一个包（PPSA29802 01.510.000）暴露出的问题，**下次拿到这类包先照单核对**：

1. 「降级补丁」zip 里 15 个文件与原始 App **逐个 md5 相同** → 纯重复包，**没有任何作用**。
2. 顶层多一个**没有 `param.json`** 的假应用目录（补丁解压产物）→ 与真 app 同 Title ID 冲突。
3. 文件夹版**双层嵌套**（`PPSA29802-app/PPSA29802-app/…`）→ 不符 SMP `scan_depth=1`。
4. `sce_sys/origin-param.json` / `target-param.json` 的**内容其实是 DDS 图片**
   （与 `pic0.dds` 同尺寸 8,294,548 B）→ 打包工具写错了，删掉无害。
5. catalog 与 bundle 文件名来自**两套打包规则**（带 hash / 不带 hash）。
6. 版本是 `01.000.000 → 01.500.000 → 01.510.000` 的**合并包**，不是单一版本号。

> 选源建议：**优先找单一版本号、不是 base+patch 合并的包。**

---

## 11. ❌ 已证伪清单 —— 不要再试

以下每一条都实测过，重复尝试纯属浪费：

| 做法 | 实测结果 |
|---|---|
| 删掉整个 `fakelib/` | **6 秒即死**（fakelib 是必需品） |
| `fakelib_mode=disabled` / `fakelib_exclude` | 同上逻辑，死路 |
| 换镜像格式 `exfat ↔ ffpkg` | 无差别 |
| 删/不删那 7 个安装流程文件（PvZ） | **表现完全一致** |
| 按 catalog 补齐 9 个带 hash 的 bundle 名 + spine（vF） | **无改善** |
| 只改 `video-out-width` 做 1080p 测试 | **测试没生效**（漏了 standardmode 那行） |
| `文件名后缀 == 文件 MD5` 做一致性校验 | 不成立（71/85 不符），是构建期 hash |
| 把 `libSceAmpr` 换成官方最新版 | 未改变静默挂起（vC） |
| 检查「不是固件门槛」 | 游戏要 FW 12.40 / SDK 10.00，主机 13.60 → **不是门槛问题** |
| 检查「数据被截断」 | 85/85 个 bundle 声明尺寸与实际**零偏差** → 不是损坏 |
| 检查「eboot 签名」 | 与能跑的 MONOPOLY 头部**逐字节同构** → 不是病因 |
| 怀疑 `ampr_emu.index` 格式 | 两者都是 `AMPRIDX3` v3 → 格式一致；且 **159 条路径逐条存在、0 缺失**，主机上也**没有** `ampr_emu.log` |
| 怀疑 `boot.config` 只改一处没生效 | 两行 `video-out-width` 全改 + 删 `120hz`（vH）→ **仍然完全一样** |
| 怀疑 Addressables 启动联网查目录 | `m_DisableCatalogUpdateOnStart=true` + `m_CatalogRequestsTimeout=5`（vH）→ **无改善** |
| 怀疑「向下兼容补丁」打错了 | 对**能正常玩的 MONOPOLY** 每次也照打同一句 NOTIFY → 不是病因 |
| 怀疑 SMP 偷偷覆盖了我们改的 fakelib | `/data/shadowmount/cache`、`/data/shadowmount/fakelib` **都不存在**，`emus/` 为**空** → 改动确实生效 |
| 怀疑系统库缺失 | 沙箱 `common/lib` 是**完整集合**（260+，含 `libSceAvPlayer`/`libSceVdecCore`）|
| 怀疑卡在播开场视频 | 包内 **一个视频文件都没有**（`*.usm/*.mp4/*.bk2/*.webm` 全无）|
| ⚠️ **怀疑 NanoDNS 挡联网导致卡死** | **结论无效** —— 它的规则只覆盖 `*.playstation.com/net`，**从没拦过游戏自己的服务器**，见 §12.1 |
| ⚠️ **怀疑要连 EA 账号服务/Sentry 遥测导致挂起** | **已实测排除**：让主机真正断外网，游戏表现**一字未变** → 见 §12.6 |
| 怀疑焦点被抢导致 CPU 降频 | SMP 日志里游戏跑满 **15 分 25 秒**，`AppFocus` **只变 2 次**（启动/退出），全程前台 → 排除 |
| 怀疑镜像/IO 走了慢路径 | `[IMG][LVD] attach try: img=5 sec=512 sec2=65536` = **BFS 快路径**，几何参数最优 → 排除 |
| 怀疑 kstuff 挂着没摘导致掉速 | SMP 日志**无任何 kstuff 记录**；同环境 MONOPOLY 流畅 → 排除 |
| 怀疑 `update_emulators=1` 用缓存覆盖了我们的 fakelib | `emulators_path`（`/data/shadowmount/emus`）**为空** → 没有可替换源，等于没开 → 排除 |
| 怀疑包内容被截断/损坏（二次确认） | `--full-verify` 165~166 文件 blake3 **逐个匹配** → 排除 |
| 怀疑"游戏已经死了只是界面卡住" | 主机日志：vH 进程 **存活 13–15 分钟**、零错误、焦点稳定 → **它是真的在爬，不是死锁** |
| **怀疑图形栈被阉割**（自制 `libSceAgc` + 缺 `libScePsml`） | **vJ 实测无改善**；且用沙箱实证「正品 Agc + Psml **确实挂进了** `common/lib`」→ **排除**（详见 §14.4）|
| **怀疑网络等待**（EA 账号 / Sentry） | 把包内两个 EA 端点改成 `.invalid`（DNS **永久失败**）→ 无改善 → **排除**（比"拔路由器"可靠得多，见 §12.6）|
| 怀疑"卡在非常早期"这个判断本身 | 沙箱 `temp0`/`download0`/`data` **全空** + 存档目录**不存在** + 沙箱 mtime 冻结 → 判断成立 |
| 怀疑 `platform-ps5-reset-temp-folder=1` 是异常值 | 这是**厂商发布的原始值**，非本包被改坏 → 不是病因 |
| 怀疑"后来的版本漏做了删 7 文件清理"导致复现 | vA/vH/vI/vJ 的 `sce_sys` 里那 7 个文件**都在**（= 没清理），表现却与清理版一致 → 与 §9 自洽 |

**仍未排除、且当前优先级最高的方向：资源读取加速层 `libSceAmpr` 版本（§15）。**
- 依据：游戏资源是 AMPRPAK4，读取必须经过 `libSceAmpr`；包内是 **255,750 B**（0.3.6.x），
  官方最新 **0.4.2.1 = 423,350 B**。
- ⚠️ 早期 `vC`（换新版 ampr）报过"无改善"，但**当时没验证沙箱**，结论不可靠 → 用 vN 重做。

> ⚠️ **证伪清单的使用纪律**：这张表里每条都对应一次**真实生效过**的实验。
> 想推翻其中任何一条，必须先证明**那次实验真的触碰到了目标** —— 两个反面教材：
> §12.1 的 NanoDNS（"拦了但没拦住"）、§14.4 的 vA~vJ（从未验证"改的库有没有挂上"）。

---

## 12. 启动期网络等待 —— 方法论留着，但实测**不是本案病因**

### 12.1 先纠正一个错误结论
早期实验用 NanoDNS 把联网挡掉，看到现象没变，于是记成「挡联网不会造成卡死」。
**这个结论是错的。** 拉 `/data/nanodns/nanodns.log` 一看，它的规则**只有**：

```
*.playstation.com / *.playstation.net / *.psndl.net  ->  0.0.0.0
```

那是**为了屏蔽 PSN**（FPS 场景的常规操作），**从头到尾没有拦过游戏自己的服务器**。
也就是说「断网能不能过」这个问题**从来没有被真正测过**。

> 教训：**先验证"你的拦截规则到底覆盖了谁"，再下"拦了也没用"的结论。**
> 规则文件/日志就在 `/data/nanodns/nanodns.log`，一眼能看。

### 12.2 这个症状族长什么样
- SMP 日志：`[GAME] started` → 60 秒 `monitoring expired`，**零错误码**（静默挂起）。
- 主机上：**过场画面一个一个地过，但每个都要很久**（≈ 每个都在等一次超时），
  最后**卡死在一个画面上**；常常伴随**没有声音**。
- 同机同假库的**别的游戏正常** —— 因为那个游戏不做账号/遥测握手。

**关键判据：卡死前有明显的"逐级变慢"。** 如果是纯加载慢，是均匀地慢；
如果是网络，是**一卡一卡、每个过场等一个固定量**，然后永久停住。

### 12.3 怎么在包里把"要连谁"挖出来
在这几个文件里直接正则扫，**它们都是未压缩明文**，无需解包工具：

| 文件 | 里面有什么 |
|---|---|
| `Media/Metadata/global-metadata.dat` | IL2CPP 元数据（`af 1b b1 fa`，v31）。**所有托管代码的字符串常量**都在这里 |
| `Media/resources.assets` | Unity 序列化资源（未压缩）。**ScriptableObject 配置**（DSN、环境、debug 开关）在这里 |
| `Media/Modules/*.prx` `Media/Plugins/*.prx` | 各程序集的导入表（能看出引用了 `libSceHttp/libSceSsl/libSceNp*`） |
| `Media/StreamingAssets/aa/*.bundle` | 本地化文案里的 URL（一般只是帮助/隐私链接，无害） |

```python
import re
d = open(path, 'rb').read()
urls = sorted({m.group().decode('latin1')
               for m in re.finditer(rb'https?://[\x21-\x7e]{8,200}', d)})
for u in urls: print(u)
# 关键字：grpc / sentry.io / accounts / .ea.com / localhost:  / diagnostics
```

然后把扫出来的域名在 PC 上 `socket.getaddrinfo()` 试一遍：
**"能解析、但连不上"就是最危险的组合**（客户端不设 deadline 时会永久阻塞）。

### 12.4 PvZ Replanted（PPSA29802）实测挖到的东西
- `global-metadata.dat` @657157 连着写了两个端点：
  `https://accounts.grpc.ea.com:443` 与 `https://accounts.grpc.int.ea.com:443`
  （`int` = 联调环境）；同一元数据里还有整套 **`Grpc.Net.Client`**。
- `resources.assets` 里有 `SentryOptionConfiguration` → `SentryOptions._dsn =`
  `https://<EMAIL>/4509928968617984`
  （EA 的 Sentry 项目），以及 `debugkit_settings` / `DebugKit/ToggleDebugMenu`。
  但同文件的 PlayerSettings 是 `"Development":false` → **是发行版，不是 dev build**。
- 这些域名（`accounts.grpc.ea.com` / `*.ingest.us.sentry.io`）**在 PC 上都能解析到美区云 IP**。
  从中国大陆访问，TCP 443 **极易被黑洞** → `connect()` 挂着不返回。

### 12.5 验证顺序（按代价从低到高）
1. **让主机真正断外网，5 分钟出结论**：拔路由器 **WAN 口**网线（或 PS5 里断开互联网），
   只要**局域网还在**就能继续 FTP。此时所有 `connect()` 立刻 `ENETUNREACH`。
   现象变了 → 确诊；一字不变 → 网络这条路也排除。
2. **等长手术**：把那些地址**等长**替换成永不解析的 RFC 2606 `.invalid` 域名
   （长度必须严格相等，否则会破坏字符串表偏移）。已验证可行的一对：
   - `https://accounts.grpc.ea.com:443`(32) → `https://accounts.grpc.ea.invalid`(32)
   - `https://accounts.grpc.int.ea.com:443`(36) → `https://accounts.grpc.int.ea.invalid`(36)
   再改 `resources.assets` 里的 Sentry DSN（public key 清零、`sentry.io`(9) → `sentry.zz`(9)）。
   效果 = 让这些请求**立刻 NXDOMAIN 失败**，而不是挂着。
3. 都不行 → 大概率就是真的与 fakelib 运行期不兼容，见 §6.2 / §14（**图形栈嫌疑**）。

### 12.6 ★ 实测结论：这条线**排除**（别再重走）
把主机**真正断外网**（路由器 WAN 口拔线，局域网保留，FTP 照用）后跑同一个 vH：
**表现一字未变** —— 既没有立刻报"网络不可达"，也没有变快，还是同样的慢。
→ 说明游戏**不是在等网络超时**。上面挖出来的 EA 端点/Sentry DSN 是真实存在的，
  但**不构成本案的瓶颈**（很可能客户端有超时或异步不阻塞）。

> 方法论保留：**"挖端点 + 真正断网"这两步依然值得做**，因为它便宜且能一票定性。
> 但本案已经做过了，结论是"不是网络"。**别再提出"改 DNS / 等长替换端点"的方案。**
> 同理，`global-metadata.dat` 里的 `Grpc.Net.Client`、Sentry DSN 都只是**存在**，
> "存在" ≠ "阻塞"。要证明阻塞必须有断网对照实验。

---

## 13. `ampr_emu` 是什么（`ampr_emu.index` 的来源）

`drakmor/ampr_emu` 是一套**游戏数据打包/读取加速**系统（`AMPRPAK4` + LZ4）：
把 `/app0` 下的文件按"读取轨迹"重排打包，提速约 30–40%。

- 索引文件 `ampr_emu.index`，头 `AMPRIDX3`（v3），收录 `/app0/...` 路径 + FNV-1a 哈希表。
- **完整部署集**（官方指南）：`ampr_emu.index` + `ampr_assets.index` + `ampr_assets.index.runtime`
  + 所有 `.pak` + 所有松散文件。
- **只要 `ampr_emu.index` 也是合法的**（"松散"部署：资源保持原始散件），
  PvZ 就是这个形态（85 个 bundle 全是原件）。
- 运行期会写自己的日志 **`ampr_emu.log`**，条目形如 `apr.pack.index.missing`、
  `apr.pack.cache.init` —— 想确认"加速层有没有找不到东西"，去找这个文件。
- 官方包 `ampr-emu-<ver>-fix.zip` 里带 `emus/` 目录和使用指南（`USER_GUIDE_EN.md`）。

---

## 14. ★★ 图形栈嫌疑：`fakelib` 三方对比法（本轮最有价值的发现）

**前提**：同一个 SMP、同一个固件下，**能跑的游戏**（MONOPOLY、PPSA25286）和
**跑不动的游戏**（PPSA29802）走的都是"全量假库"模式。所以**唯一能解释差异的，只能是包内容**。
而 `fakelib/` 就是"包内容"里最值得优先核对的部分 —— 它决定**哪些系统库被替换成替身实现**。

### 14.1 怎么做（三步，10 分钟）

把**一个跑不动的包**和**一到两个同机跑得通的包**的 `fakelib/` 放在一起逐文件对齐：

```python
import hashlib, os
NAME = {'54 14 f5 ee':'SELF正品', '4f 15 3d 1d':'FSELF自制', '7f 45 4c 46':'ELF裸'}
bases = [
    (r'D:\ps5vX\PPSAxxxxx-app\fakelib', '目标包（跑不动）'),
    (r'D:\ps5work\PPSA17419\fakelib',   'MONOPOLY（能跑）'),
    (r'E:\PPSA25286-app\...\fakelib',   'PPSA25286（能跑）'),
]
data = {}
for b, label in bases:
    data[label] = {}
    for f in sorted(os.listdir(b)):
        p = os.path.join(b, f)
        if not os.path.isfile(p): continue
        full = open(p,'rb').read()
        data[label][f] = (len(full), NAME.get(full[:4].hex(' '), '?'),
                          hashlib.md5(full).hexdigest()[:12])
    print(label, data[label])
```

**看三件事**（顺序即优先级）：
1. **文件名差集** —— 别人有、这个包**没有**的库（缺失）。
2. **同名文件的签名类型** —— 别人是 `SELF正品`、这个包是 `FSELF自制`（被替换）。
3. **同名文件的 md5** —— 逐字节相同 = 同一固件批次，可**互相借用**。

### 14.2 实测结果（PPSA29802 vs 两个能跑的）

| 库 | PPSA29802（慢） | MONOPOLY（能跑） | PPSA25286（能跑） |
|---|---|---|---|
| `libSceAgc.sprx`（图形驱动） | ❌ **自制伪签名** 322,432 B | ✅ **索尼正品** | ✅ **索尼正品** |
| `libScePsml.sprx`（着色器编译） | ❌ **完全缺失** | ✅ 正品 ~1.5 MB | ✅ 正品 ~1.5 MB |
| `libSceAgcDriver.sprx` | 正品 122,383 B | 正品 122,613 B | 正品 122,383 B |

- 两个能跑的包**无一例外**都是**正品 Agc + 带 Psml**；只有跑不动的这个用了自制图形驱动、还缺着色器库。
- `libSceAgcDriver.sprx` 在 PPSA29802 与 PPSA25286 里 **md5 完全相同** →
  两者属同一固件批次，**PPSA25286 的正品 `libSceAgc.sprx` 与这个包天生配对**，可以直接借。
- ⚠️ **一个必须记住的修正**：三个 Agc（含两个能跑的）**都引用
  `libSceShaderTranscode_minimal`** —— 所以"自制 vs 正品"的差别**不在**着色器转码路径上。
  这让「**缺 `libScePsml`**」成为理论依据更硬的那一条（两个能跑的都有，只有它没有）。

### 14.3 对应的修补版（本轮交付）

- **vJ** = 正品 `libSceAgc.sprx`（借自 PPSA25286）+ 新增 `libScePsml.sprx`。改了 2 个文件。
- **vK** = 只新增 `libScePsml.sprx`（**保留自制 Agc**），作为**单变量对照**。
  一次只改一个变量的原则在这里同样适用：vJ 若好、vK 若不好 → 是 Agc 的锅；
  两个都好 → 是 Psml 的锅；两个都不好 → 图形栈方向也不成立。

> **为什么不"先只加 Psml 再说"**：加库是**增**操作（不改现有文件行为），风险低；
> 换 Agc 是**替**操作，可能引入新变量。两个都做是为了**一次实验拿两组信息**，
> 用 vK 当对照组来归因。

### 14.4 ★ 实测结果：vJ **失败** —— 图形栈这条线**已关闭**（2026-10-16 22:37）

用户实测 vJ（正品 Agc + Psml）：**依然极慢，现象与之前完全一致**。

而且这次**做了沙箱实证**（见 §3），确认「正品 Agc + Psml 确实挂进了游戏的 common/lib」——
**改动真生效了，但还是没改善**。

→ **结论：图形栈不是病因。** 以后遇到"同机能跑、这个跑不动"，
`fakelib` 对比法**仍然值得做**（便宜、能一次看清包质量），但**别再指望"换正品 Agc/补 Psml"能修好**。
> 反向教训：`vC`（换新版 `libSceAmpr`）当初报"无改善"，但**那时没验证沙箱** ——
> 所以那个结论也不可靠，后来用 vN 重做了（见 §15）。

---

## 15. 资源读取加速层 `libSceAmpr` —— 当前唯一还没被验证排除的方向

**假设**：`libSceAmpr`（`ampr_emu` 的替身库，负责 AMPRPAK4 资源的读取）版本太老
→ 每次资源读取都走低效路径 → **能跑但极慢**。

依据：
- 这个游戏的资源是 **AMPRPAK4** 打包的，读取必须经过 `libSceAmpr`。
- 沙箱里那份 `libSceAmpr` 的调试串里能看到它在操作 `/app0/ampr_emu.index` 与 `.tmp`
  —— 而 **`/app0` 是只读镜像挂载**，写索引会失败/重试。
- 发布包里带的是 **255,750 B**（0.3.6.x 时代）；官方最新 **0.4.2.1 是 423,350 B**（大了 65%）。

做法（**必须重打包镜像**，FTP 传不了 —— 见 §2）：
```
emus 源：<插件目录>/ampr-emu-0.4.2.1apr模拟器/emus/libSceAmpr.sprx   （423,350 B）
目标  ：<包>/fakelib/libSceAmpr.sprx        ← 只换这一个文件
```
> ⚠️ 别想走"把官方 `emus/` 丢进 `/data/shadowmount/emus/` + SMP 的 `update_emulators=1`
> 让它自动替换"这条捷径 —— **FTP 写入时就会把 sprx 解密成裸 ELF**，传上去是坏的（§2）。

---

## 16. 判定纪律（这条决定了排查能不能收敛）

- **别用几十秒下结论。** 实测这个游戏走完两个 logo 就要约 **1 分钟**，首次加载
  1.5 GB 资源可能要 **5 分钟**。有一次判定发生在启动后 **46 秒**，那次判定**不成立**。
- **一次只改一个变量。** vF/vG 系列之所以有价值，就是因为相对原样版只动了少数文件。
- **交付前必须校验**：`--full-verify`，并且对 FTP 传输过的文件**回传比对**（§2）。
- **换版本前清干净**：`/data/homebrew` 与 `/data/etaHEN/games` 里同一 Title ID 只留一个，
  否则 SMP 挂载打架，**错误码还会随机漂移**，极难排查。
  上传脚本应**先删同 ID 的旧镜像再传新的**。
- **★ 下"某招没用"的结论前，必须先证明那一招真的生效过** —— 去沙箱比对（§3）。
  本仓库两次踩坑：一次是 NanoDNS「拦了但没拦住目标域名」（§12.1），
  一次是十几个版本从未验证"改的库有没有真的挂上"（§14.4）。
- **"网络不通"要用"域名永不解析"来验证，别用"拔路由器 WAN 口"。**
  后者 PS5 仍连着路由器，对外连接是**静默超时**而非立刻失败，实验等于没做。
  真管用的是**拔 PS5 网线**，或者干脆把包里的域名改成 `.invalid`（RFC 2606，永不解析）。
- **卡住 vs 在爬，要看"进程存活时长 + 沙箱有没有写入痕迹"**，不要只看
  `[MDBG] game error monitoring expired`（那只是 60 秒零错误）。

