# PS4 游戏（CUSA / PCAS …）在 PS5 上怎么跑

> 本文档解决一条**极易走错**的岔路：手里的 `*.pkg` 其实是 **PS4 包**，
> 却被当成 PS5 包去做 exFAT 镜像、丢进 `/data/homebrew` 让 SMP 挂载。
> 那条路对 PS4 游戏**根本不成立**，白折腾。

---

## 1. 30 秒判平台：看文件头魔数

```bash
python -c "print(open(r'<文件>','rb').read(4).hex(' '))"
```

| 魔数 | 含义 |
|---|---|
| `7f 46 49 48` | **PS5** 包（`\x7fFIH`），本文档主干流程适用 |
| `7f 43 4e 54` | **PS4** 包（`\x7fCNT`，CNT 容器）→ **就是本文档的场景** |
| `50 4b 03 04` | zip（不是 pkg） |

**标题 ID 前缀**：

| 前缀 | 平台 |
|---|---|
| `PPSA` / `PPSA…` | PS5 |
| `CUSA` / `PCAS` / `PCJS` / `PCSA` | PS4 |

两者**同时**成立才可靠（有人手改过 pkg）。

---

## 2. 两个「不行」，必须先说清楚

### 2.1 `ps5-dump-forge` 处理不了 PS4 包

实测（ps5-dump-forge 0.1.1）：

```
ps5-dump-forge: <x>.pkg: not a PS5 package: this is a PS4 package (\x7FCNT at offset 0)
```

它只做 PS5 的 FIH 容器 / Kraken / PFS。**没有**「PS4 pkg → exFAT」的现成工具。
所以别指望「先转成镜像再挂」这条路。

### 2.2 SMP **不认** PS4 游戏

ShadowMountPlus 只扫 PS5 游戏（判据是 `sce_sys/param.json`）。
PS4 游戏是 `sce_sys/param.sfo`，容器格式也完全不同。
把 PS4 的 exFAT 镜像放进 `/data/homebrew` 只会被跳过。

> **PS4 游戏必须由主机的 PS4 模拟器从 pkg 装载**，不是由一个「PS5 游戏的挂载器」挂载。

---

## 3. 正确路径：PS4Mount（从 U 盘跑 PS4 fake pkg）

项目：`gasb07/ps4mount`（GPL-3.0，C 写的 ELF 载荷）。载荷文件名通常就是 `ps4mount.elf`。

**机制**：扫描 U 盘里的 PS4 **fake** pkg → 用 `sceAppInstUtilAppInstallTitleDir`
把标题注册进 PS5 库、并把安装目录指向 U 盘 → 游戏**从 U 盘直接运行**，不占内置空间。

### 3.1 U 盘目录约定（官方 README，务必照做）

| 阶段 | 位置 |
|---|---|
| **初始放入** | U 盘**根目录**，`.pkg` 直接扔进去，**文件名无所谓** |
| PS4Mount 处理之后 | `<U盘>/ps4/CUSAxxxxx/{app.pkg, patch.pkg, addcont/CUSAyyyyy/<LABEL>/ac.pkg}` |

- 「更新放在本体旁边会被自动配对」。
- ⚠️ **`ps4` 文件夹不能作为扫描目录** —— 它放的是已经搬好的游戏。
  以后加新游戏：把新 pkg 拷到**根目录**。
- 多驱动器会拖慢主机界面；理想情况**单分区**。

### 3.2 环境要求

- 越狱 PS5，**带 fake PKG 支持**（`etaHEN` + `kstuff` 那条路）。
- ELF loader（常见端口 9021）。
- **klogsrv**（端口 3232 或等价设施）—— 载荷靠读 `/dev/klog` 判定游戏启动/删除。
  没有它，游戏**注册了也起不来**。
- U 盘必须 **exFAT**。README 未规定簇大小。

### 3.3 已知风险

- 项目自称开发中，**有报告会导致主机数据库损坏**；重建数据库后通过它添加的游戏
  可能暂时从游戏库消失。**动手前备份存档。**
- 强制重启可能丢未保存数据。
- 载荷里有固件门槛字符串：
  `PS4Mount x.y.z: firmware %s is not supported yet. To protect the system database, no games are added.`
  → 若日志出现这句，就是**它还没适配你这版固件**，改包无用。
- 只支持 **fake** pkg，不支持零售 pkg。

### 3.4 「能跑到哪个固件」的参照（社区表，非官方）

PS5 的 PS4 模拟器能运行「要求不超过某个 PS4 固件」的 PS4 游戏：

| PS5 固件 | 可跑 PS4 游戏（其所需 PS4 固件上限） |
|---|---|
| 2.xx | 8.03 |
| 4.xx | 9.04 |
| 6.xx | 10.50 |
| 8.xx/9.xx | 11.50 |
| 10.xx | 12.00 |
| 11.xx | 12.50 |
| 12.xx | 13.00 |
| **13.xx** | **13.52** |
| 14.xx | 14.00 |

补充：社区反馈「**PS4 backport（降级）FPKG 在带 kstuff 的越狱 PS5 上也能正常工作**」。
所以手上的包是 5.05–6.72 的降级版也没关系。

---

## 4. 顺带：把「一堆 pkg」收拾成一个 exFAT **整盘镜像**

有时目标就是「一个文件，写盘即用」。这时不需要任何 pkg 工具 —— **文件原样放进去**即可。

**做法（只用 Windows 自带的 diskpart，不需要 Hyper-V 或第三方工具）**：

```
create vdisk file="E:\out.vhd" maximum=8192 type=fixed
select vdisk file="E:\out.vhd"
attach vdisk
create partition primary
format fs=exfat unit=65536 quick label=CUSA15884
assign letter=U
```

→ 把 pkg 复制到 `U:\` 根目录 → 再：

```
select vdisk file="E:\out.vhd"
detach vdisk
```

→ **fixed VHD = 裸盘数据 + 尾部 512 B 的 `conectix` footer**，
把最后 512 B 去掉就是裸 `.img`（可直接用 Rufus / balenaEtcher / Win32DiskImager 写盘）：

```python
import os
vhd, img = r'E:\out.vhd', r'E:\out.img'
n = os.path.getsize(vhd) - 512
assert open(vhd,'rb').read(0) == b''  # 占位
with open(vhd,'rb') as f:
    assert f.seek(n) or f.read(8) == b'conectix'
with open(vhd,'rb') as fi, open(img,'wb') as fo:
    left = n
    while left:
        b = fi.read(min(8*1024*1024, left))
        if not b: break
        fo.write(b); left -= len(b)
```

现成脚本：`scripts/mkexfat.py`。

**注意事项**

- **整盘镜像**会覆盖目标盘的分区表；写盘前备份 U 盘。
- 写完镜像后，U 盘上超出镜像的部分是**未分配**空间。
  ⚠️ **Windows 自带的「磁盘管理」不能扩展 exFAT 分区**（`扩展卷` 只对 NTFS 有效），
  要用 DiskGenius / 傲梅分区助手之类。
- **更省事的路子**：如果只是要玩游戏，直接把 pkg 拷到已格式化为 exFAT 的 U 盘根目录，
  效果与镜像完全一样。镜像的价值在于「一次写盘、布局不会错、能存档复用」。
- 校验要**独立做**，别信工具自述：解 MBR → VBR → 根目录项 → 逐文件 MD5 比对。
  `scripts/probe_exfat.py` 是给 **PS5** 镜像用的（看 SELF 魔数），
  PS4 包没有那套 SELF 结构，别用它下结论。

---

## 5. U 盘插哪个口 / 换口会不会影响游戏（2026-10-17 实测）

PS4 游戏全部从 U 盘读数据，所以**接口速率直接等于加载速度**。

### 5.1 PS5 标准版（CFI-1000）的四个口

| 位置 | 接口 | 官方标注 | 实际 |
|---|---|---|---|
| 正面 | USB Type-A | Hi-Speed USB | **USB 2.0，实测上限 ~37 MB/s** |
| 正面 | USB Type-C | SuperSpeed 10Gbps | USB 3.2 Gen 2 |
| 背面 ×2 | USB Type-A | SuperSpeed 10Gbps | USB 3.2 Gen 2 |

> 「Hi-Speed USB」在 USB-IF 术语里就是 **USB 2.0（480 Mbps）**，不是"高速"的意思。
> 10 Gbps 也不叫 USB 3.0（那是 5 Gbps / Gen 1）。

### 5.2 实测：同一块盘、同一个文件、只换口

| 位置 | 300 MB 读取 | 吞吐 |
|---|---|---|
| 前置 USB-A | 8.13 s / 8.06 s | **36.9 / 37.2 MB/s** |
| 背面 USB-A | 2.69 s / 2.71 s | **111.4 / 110.7 MB/s** |
| 内置 SSD（对照组） | 2.67 s | 104 ~ 112 MB/s |

背面那一组和内置 SSD **完全同速**，说明已经顶到千兆网天花板
（FTP 走网线约 112 MB/s），U 盘真实速度只会更高。

**测量方法**：`scripts/usb_speed.py`（纯 FTP 读，不需要任何主机端载荷）。
关键是 offset 要取一段**之前没读过**的数据，否则命中页缓存数字会虚高；
同时必须测一次内置盘做对照，否则分不清是 U 盘慢还是网络慢。

### 5.3 换口 / 换盘会不会导致游戏跑不起来？——不会

实测：同一块 U 盘从前置 2.0 口换到背面 10 Gbps 口，**游戏照常启动**，只是变快。
原因有三条：

1. 挂载点是**按枚举序号**给的（`/mnt/usb0`…`usb7`），**单盘插拔恒为 `usb0`**，
   路径不变；实测 8 个挂载点里只有 `usb0` 有内容，其余全空目录。
2. PS4Mount **每次启动都会重新扫描**并重新注册，不依赖上一次的枚举结果。
3. `/data/ps4mount/<TID>.src` 里记的是路径字符串，不是设备句柄。

**唯一的坑**：同时插**两块以上** USB 存储时，序号可能互换
（原来在 `usb0` 的盘变成 `usb1`），此时 `.src` 里的路径失效 →
面板上游戏还在但点开进不去。处理：拔到只留一块盘 → 重启 PS4Mount 重新扫描。

### 5.4 纪律

- **U 盘固定插背面 USB-A**；前面那个 2.0 口留给手柄/VR 设备。
- 换口或重新插拔 U 盘之后，**重启一次 PS4Mount**（它会重新扫描注册），
  不要直接点游戏——那就是「先点游戏后开 PS4Mount」的翻车姿势（§6.5）。
- 加载慢、贴图糊、切场景卡：先按 5.2 测一次，`< 50 MB/s` 就是插错口了。

---

## 6. 运行期排障：点开游戏「停在主画面没反应」（2026-10-17 实测实锤）

症状：昨天能跑，今天点开一直停在「进入游戏」主画面，**无报错、无错误码**。
⚠️ 用户最容易先怀疑「U 盘没插好 / 游戏坏了」——都不是。

### 6.1 真正的病因（日志实锤，两个独立证据）

1. **PS4Mount 日志**（`/data/ps4mount/log.txt`，FTP 可取）里 klog 行反复出现：
   ```
   The version is newer for DownloadData[0] than App   (错误码 0x80a4003c)
   ```
   主机在**无限重试启动**，每秒报一次——所以画面「安静地停着」，没有弹窗。
2. **机制**：PS5 启动 PS4 游戏前，会逐字节比对
   `/system_data/priv/appmeta/<TITLE_ID>/param.sfo` 与**更新包**的 param.sfo。
   PS4Mount 注册时写入的是**本体**（如 01.00）的 sfo，而更新包（01.15）已暂存
   → 比对不一致 → 拒绝启动。

**PS4Mount 自己有修复函数 `enforce_patch_sfo()`**（把 appmeta 的 sfo 重写成更新包版本），
日志里成功的标志是一行：
```
priv param.sfo was not the update's, rewritten
```
这行**出现过** = 修复完成，能跑；**没出现过** = 修复被跳过，必然卡画面。

### 6.2 为什么修复会被跳过：0.5.1 注册竞态

0.5.1 的注册日志里出现 `AppInstallAll=(still running)`——它**没等注册完成**就继续走，
修复步骤在竞态下被跳过。昨天成功是因为「删除→重新添加」的循环偶发把状态洗干净了。

### 6.3 修复路径（按顺序试，前一步成功就不用走后一步）

1. **升级到 0.6.0**（2026-10-16 发布，修的正是注册竞态）：
   - 从 `github.com/gasb07/ps4mount/releases` 下 `ps4mount.elf`，**核对官方 .sha256**；
   - 主机载荷在 `/data/pldmgr/payloads/local/ps4mount/ps4mount.elf`：
     FTP 先传 `ps4mount.elf.new` → 回读校验 → 旧版 `rename` 为 `.v0.5.1.bak` → 新版就位
     （⚠️ 别直接覆盖，中途断传会留下坏 ELF）；
   - 面板 `POST /api/stop` 停旧进程，再从 pldmgr 重新启动载荷。
2. **干净地「移除→重新添加」**（0.6.0 下重做这个循环即修复，全程可远程）：
   ```
   POST http://<PS5 IP>:8770/api/unmount?title_id=CUSAxxxxx   # 移出资料库（pkg 留在 U 盘）
   POST http://<PS5 IP>:8770/api/mount?title_id=CUSAxxxxx     # 重新添加
   ```
   前提：游戏**不在 running 状态**——卡住时先在主机上按 Options→关闭应用程序。
   成功的日志特征：**没有** `(still running)`，而是 `AppInstallAll=0x00000000: 1 of 1 title(s) registered`；
   0.6.0 修复后注册时直接写对版本，**不会再出现** `rewritten` 行——别把它当失败信号。
3. **仍不行才查 sfo 本体**：从 FTP 取 `/system_data/priv/appmeta/<TID>/param.sfo` 解析
   （PSFO 头 `magic(4s) ver(I) key_off(I) val_off(I) n(I)`，索引项 16 B：
   `koff(I) fmt(I) vlen(I) vmax(I)`，值在 `val_off + voff`）看 APP_VER 是否=补丁版本。
   注意：sfo 文件内容对**不代表**数据库版本记录对——数据库才是启动检查的对象。

### 6.4 面板与诊断 API（8770 端口）

| 端点 | 作用 |
|---|---|
| `GET /api/games` | 列表：title_id / name / **state**（ready·removed·running·internal）/ version / update_issue |
| `POST /api/unmount?title_id=X` | 移出资料库（running 状态会被拒） |
| `POST /api/mount?title_id=X` | 添加进资料库 |
| `POST /api/rescan` | 强制重扫 U 盘 |
| `POST /api/stop` | 停止 PS4Mount 自身 |
| `GET /api/log` | 当前日志 |

`state=running` 但游戏实际没在跑 → 是面板状态没刷新，去主机上关掉即可。

### 6.5 启动顺序纪律（每件事都对应一次实锤翻车）

> **跑破解 → 开 PS4Mount（等扫描完成）→ 再点游戏。**

先点游戏后开 PS4Mount = 装载环境没起来 = 停在主画面（本次事故的表层原因）；
注册竞态 = param.sfo 版本不匹配 = 也停在主画面（本次事故的深层原因）。
两种病因症状完全一样，**别靠猜，拉 `/data/ps4mount/log.txt` 找 `0x80a4003c` 一锤定音**。

---

## 7. 本次实测记录（2026-10-16，双点医院 CUSA15884）

**输入**：7 个 PS4 fake pkg，全是 `7f 43 4e 54`。

| 文件 | 大小 | 角色 |
|---|---|---|
| `...v1.00_[6.72]_...pkg` | 2,075,852,800 | 本体（要求 PS4 6.72） |
| `...v1.15_BACKPORT_[5.05-6.72]_...pkg` | 2,524,119,040 | 更新补丁（已降级） |
| `Close Encounters` / `Off.The.Grid` / `Retro.Item.Pack` / `Exhibition.Item.Pack` | 各 1,048,576 | 4 个 DLC |
| `EP0177-...LANGPACKCHINESE0-A0000-V0100.pkg` | 1,572,864 | 中文语言包 |

**一个值得记的判断**：那 4 个 DLC **正好各是 1 MiB 整数**，极像截断/空壳。
实测否定：头部入口表能读到 `param.sfo` / `icon0.png`，尾部 512 KiB 里 **74% 是真实数据**
→ **不是截断**。它们属于「解锁型附加内容」（素材已在本体，pkg 只解锁），所以小。
→ 教训：**「大小恰好是整数」不足以判定 pkg 残缺**，要去看入口表与数据密度。

**产出**：`E:\29802\ps4_CUSA15884_8G.img`
8.000 GiB，MBR 类型 0x07 起始 LBA 2048，exFAT 512 B 扇区 / **64 KiB 簇**，
根目录 7 个 pkg **全部连续存储**，**7/7 MD5 与源文件一致**。

---

## 8. 一句话判据（下次直接照这个走）

```
pkg 头是 7f 43 4e 54（CUSA…）
  → PS4 包，ps5-dump-forge 与 SMP 都用不上
  → 走 PS4Mount：exFAT U 盘 + pkg 放【根目录】+ etaHEN/kstuff + klogsrv
  → 启动顺序：跑破解 → 开 PS4Mount → 再点游戏
  → 停在主画面无反应 → 拉 /data/ps4mount/log.txt 找 0x80a4003c（§6）
  → 加载慢/贴图糊 → 先测吞吐（references §5，scripts/usb_speed.py）：
      ~37 MB/s = 插在前置 2.0 口，换背面；~111 MB/s = 正常（千兆封顶）
  → 换口/换盘不影响能否运行，但换完要重启 PS4Mount 重新扫描
  → 想要「一个文件」就做整盘 exFAT 镜像（diskpart + fixed VHD，剥尾部 512 B）
```
