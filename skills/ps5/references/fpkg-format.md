# FPKG 结构与 exFAT 镜像格式

手工排查二进制问题、或需要自己写解析脚本时读本文。

## 一、PKG 文件头 magic

读文件前 4 字节判断平台：

| magic（hex，文件顺序） | 含义 |
|---|---|
| `7F 43 4E 54` | PS4 pkg（CNT 容器，`\x7F CNT`） |
| `7F 46 49 48` | **PS5 pkg（FIH 容器，`\x7F FIH`）** |
| `7F 50 41 47` | PS Vita pkg（`\x7F PAG`） |

```python
head = open(path, "rb").read(4)
{"\x7fCNT": "PS4", "\x7fFIH": "PS5", "\x7fPAG": "PS Vita"}.get(head.decode("latin1"))
```

### SELF magic：**这一项决定镜像能不能被侧载运行**

`eboot.bin` / `*.prx` / `*.sprx` 都是 SELF（Sony 签名容器），前 4 字节的 magic 区分平台与**签名类型**：

| magic（hex，文件顺序） | 小端值 | 含义 |
|---|---|---|
| `54 14 F5 EE` | `0xEEF51454` | **PS5 原生 SELF（Prospero）＝正品签名** —— 给 **FPKG 安装流程**用 |
| `4F 15 3D 1D` | `0x1D3D154F` | **FSELF 伪签名**（文档里也写作 Orbis/PS4 兼容 magic）—— 给**侧载**用 |
| `7F 45 4C 46` | `\x7fELF` | 裸 ELF（已完全解密） |

```python
m = open(path, "rb").read(4)
{bytes.fromhex("5414f5ee"): "正品签名（安装用）",
 bytes.fromhex("4f153d1d"): "FSELF（侧载就绪）",
 bytes.fromhex("7f454c46"): "裸 ELF"}.get(m, "?")
```

**关键结论（实测，2026-10）**：从 `.pkg` 解出来的应用，所有 SELF 都是 `54 14 F5 EE`；
而**能侧载运行**的发布版（folder / exfat / ffpkg）把**全部** SELF 改成了 `4F 15 3D 1D`。
两者**大小完全相同，逐字节只差开头那 4 个字节** —— 这 4 字节就是全部差异。

实测样本（PPSA17419 MONOPOLY v01.005.000，同版本两份来源）：

| 项目 | pkg 解出 | 侧载发布版 |
|---|---|---|
| `eboot.bin` | `54 14 F5 EE`，34,136,733 B | `4F 15 3D 1D`，**字节数完全相同** |
| `sce_module/*.prx`（6 个） | `54 14 F5 EE` | `4F 15 3D 1D` |
| `Media/Modules/*.prx`、`Media/Plugins/*.prx`（9 个） | `54 14 F5 EE` | `4F 15 3D 1D` |
| `sce_sys/about/right.sprx` | `54 14 F5 EE` | `4F 15 3D 1D` |
| `fakelib/libSceAgc.sprx` 等 | — | `54 14 F5 EE`（**没改**，运行时挂载不需要） |
| `fakelib/libSceAmpr.sprx` | 无 | `4F 15 3D 1D` |

比对脚本（找出「改了哪些、改了什么」，同尺寸文件非常有效）：

```python
a, b = open(pa,"rb"), open(pb,"rb")
off, diffs = 0, []
while True:
    ba, bb = a.read(4<<20), b.read(4<<20)
    if not ba and not bb: break
    for i in range(min(len(ba), len(bb))):
        if ba[i] != bb[i]: diffs.append((off+i, ba[i], bb[i]))
    off += len(ba)
print(len(diffs), [(hex(o), hex(x), hex(y)) for o,x,y in diffs[:20]])
```

### 侧载镜像的文件取舍（2026-10-16 A/B 实测确定）

这是本文件最实用的一张表。**侧载 ≠ 安装**：安装流程的产物留在镜像里会让运行时授权校验走错路。

**✅ 必须保留**

| 文件 | 作用 |
|---|---|
| `sce_sys/param.json` | **最关键**，缺它 SMP 直接报 missing/invalid param.json，游戏不上架 |
| `sce_sys/nptitle.dat`、`disc_info.dat`、`keystone`、`pfs-version.dat` | 标题注册 / 光盘标识 / 密钥 / PFS 版本 |
| `sce_sys/uds/npbind.dat`、`sce_sys/trophy2/npbind.dat` | NP 绑定 / 奖杯绑定 |
| `fakelib/` 全部（正品签名图形库 + `libSceAmpr.sprx` 等） | 降级补丁 + 授权模拟，运行时由 unionfs 挂进游戏沙箱 |
| `ampr_emu.index` | AMPR 路径解析索引（`AMPRIDX3` 头），与 `libSceAmpr.sprx` 配套 |
| 图标 `icon0.*` / `pic*.png`、`sce_sys/about/right.sprx`、`ext_info.dat` | 界面与签名 |
| `sce_sys/playgo-scenario.json` | 场景描述，与下面那 3 个 `.dat` 不同，**可留** |

**❌ 必须去掉的 7 个（零售安装流程的产物）**

| 文件 | 为什么必须去掉 |
|---|---|
| `sce_sys/license.dat`、`license.info` | 安装时由 PSN 授权流程写入的凭证。侧载内容里留着它，运行时的授权路径会走错 → 应用启动后崩（`CE-108255-1` / `CE-108264-1`） |
| `sce_sys/playgo-chunk.dat`、`playgo-ficm.dat`、`playgo-hash-table.dat` | PlayGo 分段下载元数据，只服务安装流程 |
| `sce_sys/origin-param.json`、`target-param.json` | 「基础版 + 升级包」合并流程的残留 |

**可留不可留都行**：发布站水印（`2468c.com.txt`、`更多资源请访问….url`、`readme.txt`）。
**证据**：用户机上能正常跑的文件夹游戏 `E:\PPSA25286-app` 就带这两个水印，
而它**没有**上面那 7 个文件 —— 所以水印不是病因。

> **实测 ①**（PPSA17419 MONOPOLY，镜像格式）：同一份通用发布版，原样转出的镜像报
> `CE-108255-1`；**只删掉上面这几项**重新转出的镜像即正常运行。250 → 242 文件。
> **实测 ②**（PPSA29802 PvZ Replanted，文件夹格式）：那 7 个文件 **7/7 齐全** → 同一病因。
> 清理后重打包，156 文件全量 blake3 校验通过。

> **⚠️ 适用范围限定（2026-10-16 后续实测补充）**
> 上表的「必须去掉」只在**老引擎包**上被验证（MONOPOLY = Unity 5.x 传统管线）。
> 在 **Unity 6000 + Addressables + `ps5nggc`** 的新引擎包（PvZ Replanted）上，
> 删与不删这 7 个文件，**SMP 日志表现完全相同**（60 秒无错误后静默挂起）→ 配方**无效**。
> 判断方法：包里有没有 `Media/StreamingAssets/aa/catalog.bin`。
> **这类包请直接看 `runtime-diagnosis.md`。**

### 文件夹格式的目录层级（另一个独立坑）

SMP 官方 README 原文要求「**no extra nesting level**」，默认 `scan_depth=1` 只扫第一层子目录：

```
homebrew/
└── PPSAxxxxx-app/        ✅ 正确
    ├── eboot.bin
    └── sce_sys/param.json

homebrew/
└── PPSAxxxxx-app/
    └── PPSAxxxxx-app/    ❌ 多一层 → missing/invalid param.json
        ├── eboot.bin
        └── sce_sys/param.json
```

发布站下载的包**大量是双层嵌套**（`PPSA29802-app/PPSA29802-app/…`），
拷到 homebrew 前**必须压平**。

**还要当心「补丁解压出的假应用」**：发布站常把降级补丁单独打一个 zip
（如 `降级补丁-4xx ….zip`），它里面是 `eboot.bin` + `fakelib/` + `Media/…` + `sce_sys/about/right.sprx`
—— **没有 `param.json`**。如果解压到顶层，就在顶层生成了一个「看着像游戏、其实没 param.json」的
半成品目录。SMP 扫到它就会报错，或与真正的 app 目录形成 `duplicate titleId` 冲突。
**那个顶层目录要删掉或移出扫描路径。**

### 判断 eboot.bin 是否真的依赖 fakelib

直接搜字符串（**不要**用 `inspect` 的 `backport:` 字段下结论 —— 那只是「fakelib 目录存在」）：

```python
data = open("eboot.bin","rb").read()
for pat in [b"fakelib", b"/app0", b"libSceAgc", b"libScePsml", b"common/lib"]:
    print(pat, data.count(pat))
```

- `fakelib` 出现 **0 次** → eboot 不硬编码 fakelib 路径，backport 靠运行时 unionfs 挂载。
- `libSceAgc` 出现上百次是正常的（任何 PS5 游戏都导入它），不代表依赖 fakelib。
- 注意：**「不含 fakelib 引用」不等于「可以安全删 fakelib」** —— 实测删掉后报错依旧，
  发布版本身也带 fakelib。默认原样保留。

> **fakelib 是必需品（2026-10-16 决定性实测）**：删掉整个 `fakelib/` 后，
> SMP 日志里只剩 `[FAKELIB] directory mounted`、**没有** `game mounted`，
> 进程 **6 秒后**以 `0xa0020318 (SYSTEM_ABNORMAL_TERMINATION_REQUEST)` 死掉；
> 保留 fakelib 才能走到游戏 logo。→ `fakelib_mode=disabled` / `fakelib_exclude` 是死路。
> 另外：fakelib 里几个库保持**正品签名 `54 14 F5 EE`** 是**正常**的（运行时挂载不看它），
> 需要是 FSELF 的只有**应用自身**的模块。

### `ampr_emu` 是什么（`ampr_emu.index` 的来历）

`drakmor/ampr_emu` 是一套**数据读取加速**系统（`AMPRPAK4` 容器 + LZ4）：把 `/app0` 下的文件
按实际"读取轨迹"重排打包，官方称提速约 30–40%。

| 项 | 说明 |
|---|---|
| `ampr_emu.index` | 路径解析索引，头 `AMPRIDX3`（v3），收录 `/app0/...` 路径 + FNV-1a 哈希表 |
| **官方完整部署集** | `ampr_emu.index` + `ampr_assets.index` + `ampr_assets.index.runtime` + 所有 `.pak` + 所有松散文件 |
| **只带 `ampr_emu.index` 也合法** | 即"松散部署"（资源保持原始散件），实测 PvZ 就是这种形态（85 个 bundle 全是原件） |
| 运行期日志 | `ampr_emu.log`，条目形如 `apr.pack.index.missing`、`apr.pack.cache.init` —— 想确认加速层有没有找不到东西就找它 |
| 官方最新库 | `libSceAmpr.sprx` release **0.4.2.1 = 423,350 B**；很多发布包自带的那份只有 **255,750 B**（0.3.6.6 时代） |

> ⚠️ 想升级 `libSceAmpr.sprx` **不能经 FTP 上传**（ftpsrv 会透明解密 SELF），
> 只能在 PC 上换文件后重打包镜像。且实测把它换成 0.4.2.1 **并未**改变静默挂起现象。

## 二、PS5 FPKG 的典型内部布局

以一次真实样本（MONOPOLY / PPSA17419 / 2.4 GB）为例：

```
[0x00000000]  FIH 头（magic 7F 46 49 48）+ 外置 PFS 镜像 —— 占绝大部分体积
[  ~2.377 GB]  元数据区
[尾部]         config ZIP：以 PK\x03\x04 开头，末尾有标准 EOCD(PK\x05\x06)
```

要点：

- 游戏本体是一个 **PFS 镜像**，可能整块 **Kraken 压缩**，也可能是 **plaintext**。
- 「plaintext」在 inspect 里显示为 **`plaintext (PPRPLAIN-NOAUTH)`** —
  **NOAUTH 表示不需要 passcode / 密钥**，可以直接解。
- 尾部追加的 **ZIP 只是 config 区**（含若干元数据文件），
  看到 `PK\x05\x06` 不代表整个 pkg 是 zip，只是尾巴这一小段是。
- 因此**不要**用通用解压工具去解 `.pkg`——只会拿到尾部那点元数据。

`ps5-dump-forge inspect` 会正确报告标题、标题 ID、`content_version`、固件要求、
文件数、压缩方式、image mode 和 findings，不需要自己解析。

## 三、exFAT 引导扇区字段

引导扇区共 512 字节，关键偏移（小端）：

| 偏移 | 长度 | 字段 |
|---|---|---|
| 0x03 | 8 | 文件系统名，必须是 `EXFAT   `（3 个尾随空格） |
| 0x40 | 8 | `PartitionOffset` 分区偏移（扇区） |
| 0x48 | 8 | `VolumeLength` 卷长度（扇区） |
| 0x50 | 4 | `FatOffset` FAT 起始（扇区） |
| 0x54 | 4 | `FatLength` FAT 长度（扇区） |
| 0x58 | 4 | `ClusterHeapOffset` 簇堆起始（扇区） |
| 0x5C | 4 | `ClusterCount` 簇总数 |
| 0x60 | 4 | `FirstClusterOfRootDirectory` 根目录首簇 |
| 0x64 | 4 | `VolumeSerialNumber` 卷序列号 |
| 0x68 | 2 | `FileSystemRevision` |
| 0x6A | 2 | `VolumeFlags` |
| 0x6C | 1 | `BytesPerSectorShift`（9 → 512 B） |
| 0x6D | 1 | `SectorsPerClusterShift`（7 → 128 扇区 = 64 KiB） |
| 0x6E | 1 | `NumberOfFats` |
| 0x70 | 8 | 卷标签（UTF-16LE 前 11 字符） |

```python
import struct
bs = open(image, "rb").read(512)
assert bs[3:11] == b"EXFAT   "
part_off, vol_len = struct.unpack_from("<QQ", bs, 0x40)
fat_off, fat_len = struct.unpack_from("<II", bs, 0x50)
heap_off, cluster_cnt = struct.unpack_from("<II", bs, 0x58)
root_clu, serial = struct.unpack_from("<II", bs, 0x60)
bps_shift, spc_shift, nfats = bs[0x6C], bs[0x6D], bs[0x6E]
sector = 1 << bps_shift          # 512
cluster = sector << spc_shift    # 65536
```

**簇首字节地址** = `heap_off * sector + (cluster_index - 2) * cluster`
（簇从 2 开始编号）。

## 四、根目录条目

每个条目 32 字节，第 1 字节是类型。按条目类型遍历：

| 类型字节 | 含义 |
|---|---|
| `0x00` | 结束标记，停止遍历 |
| `0x83` | 卷标签（第 2 字节 = 字符数，随后是 UTF-16LE 标签） |
| `0x85` | 文件目录项（`File`），第 2 字节 = 后续条目数 `sec` |
| `0xC0` | 流扩展：**属性在条目偏移 0x04**，首簇在 0x14，数据长度在 0x18（8 字节） |
| `0xC1` | 文件名：从偏移 0x02 起，每 2 字节一个 UTF-16LE 字符，共 15 个 |

> **易错点**：属性字段在**条目起点 + 0x04**（不是 +0x03）。
> 判断目录用 `attr & 0x10`。偏移写错会得到一串乱码名字或错误类型。

标准 PS5 应用转储的根目录应包含：

```
eboot.bin          # 主程序（通常几十 MB）
sce_sys/           # 系统元数据（param.json、图标、奖杯、nptitle、npbind…
                   #  ← 注意：license.dat / license.info / playgo-*.dat 要删掉，见上文取舍表）
sce_module/        # 系统模块
fakelib/           # 模拟库（backport 补丁 + 授权模拟；原样保留）
ampr_emu.index     # AMPR 路径解析索引（与 fakelib/libSceAmpr.sprx 配套，保留）
Media/             # 游戏资源
```

缺 `eboot.bin` 说明这不是完整的应用转储。

**两种来源的形态差别（选源时按这个判断）**：

| 形态 | 典型路径/命名 | 特征 | 用途 |
|---|---|---|---|
| **侧载就绪**（首选） | `PPSAxxxxx-app 01.00x.000/`、`PPSA17419 MONOPOLY (01.005.000)/` | eboot + 全部应用模块是 `4F 15 3D 1D`；带 `fakelib/` + `ampr_emu.index` | **先删掉上面那 8 项**，再 `--to exfat/ffpkg` |
| **安装用 pkg** | `EP0001-PPSAxxxxx_00-GAME….pkg` | SELF 是 `54 14 F5 EE`；无 nptitle / npbind / ampr | 转成镜像**大概率报 `CE-108264-1`**，能换源就换 |
| **解密转储** | 顶层 eboot + 内含 `decrypted/` 子目录（里面有 `7F 45 4C 46` 裸 ELF） | 供解包/研究用 | 不是直接可跑的镜像源 |

**注意**：「侧载就绪」只解决了 SELF 魔数问题，**不等于就能跑** —— 还必须做上面的旁挂文件清理。
这两步都做完才是本次实测跑通的完整配方。

## 五、ShadowMountPlus（SMP）挂载规则

1. **几何**：512 B 扇区 + 64 KiB 簇，即 `BytesPerSectorShift=9`、`SectorsPerClusterShift=7`。
   这是 SMP 的快路径，非此几何可能挂不上。
   `ps5-dump-forge` 默认输出即满足。
2. **文件名长度**：**不含扩展名的主干 ≤ 63 字节**（UTF-8 字节数，非字符数）；
   `.ffpfsc` 收紧到 **58 字节**。超限则 SMP 无法挂载。
3. **卷标签**：通常为标题 ID（形如 `PPSA17419`）。
4. **挂载点**：SMP 扫描 U 盘/外置盘（`/mnt/usb0..7`）自动挂载；
   盘本身可以是 exFAT 或 FAT32。
5. **格式选择**：SMP 官方推荐 `ffpkg`；`ffpfsc` 只读但最小；`exfat` 通用性最好、可读写。

## 六、命名约定

建议 `<标题ID>_<标题>_<版本>.<扩展名>`，例如
`PPSA17419_MONOPOLY_01.005.000.exfat`。
标题里的特殊字符（`®`、`™`、空格、`:`）在自动命名时应替换为 `_`，
既避免路径问题也控制字节长度。

## 七、校验建议

两个层面都要做：

1. **工具全量校验**：`convert ... --full-verify`，逐字节重读并比对（样本会输出
   每个文件的 blake3 结果）。
2. **独立结构校验**：自己解析引导扇区 + 根目录（见上文代码），确认
   文件系统名、几何（512/65536）、卷标签、`eboot.bin` 的存在与大小。

`scripts/forge.py verify` 已实现第 2 种。
