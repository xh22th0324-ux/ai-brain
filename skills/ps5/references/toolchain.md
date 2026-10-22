# PS5 工具链能力矩阵

## 首选工具

### quer3q/ps5-dump-forge

| 项 | 值 |
|---|---|
| 仓库 | `github.com/quer3q/ps5-dump-forge` |
| 版本 | v0.1.1（本文撰写时） |
| 语言/形态 | Rust，纯 CLI |
| 体积 | Windows x86-64 CLI 包约 8 MB（解压后约 21 MB） |
| 依赖 | 无。底层自带 ps5upload 的 Rust 引擎，含 FPKG 的 FIH / Kraken / PFS / CNT 读写 |

**发布包命名**：`ps5-dump-forge-<ver>-<platform>.zip`，platform 形如 `windows-x86-64`、
`linux-x86-64`、`macos-aarch64`。

> **坑位**：同一个 release 里还有 `...-windows-x86-64-webview2.zip` 之类的 GUI 变体，
> 体积约 309 MB，命令行能力完全相同。**一律选不含 `webview2` / `gui` 的那个**。
> `scripts/forge.py` 已内置此偏好（在候选里取体积最小的非 GUI 包）。

**子命令**（注意：**没有** `extract`、`list` 这类命令，解包走 `convert --to folder`）：

```
inspect <path> [--json] [--password-stdin]
convert <source> --to folder|exfat|ffpkg|ffpfs|ffpfsc|pkg|lz4
        [--inner exfat|ffpkg|ffpfs] [-o <output>] [--threads N]
        [--remove-backport] [--full-verify]
        [--kraken fast|balanced|smallest|stored]
        [--level 0..9]
        [--lz4-profile <toml> | --lz4-traces <zip|dir|journal>]
        [--lz4-trace [--lz4-trace-space <MiB>] | --lz4-unpack | --lz4-unpatch | --lz4-pack]
convert <image.exfat|image.ffpkg> --lz4-in-place (...) [--full-verify]
lz4-patch <folder>
lz4-unpatch <folder>
lz4-profile <source> [...] [-o <out.toml>] [--password-stdin]
serve [--port N] --root <dir> [--root <dir>]...
```

**输入类型**：游戏文件夹、镜像（`.exfat` / `.ffpkg` / `.ffpfs` / `.ffpfsc` / `.pkg`）、
压缩包（`.zip` / `.7z` / `.rar`，含分卷的首卷）。压缩包**就地读取，不解压到磁盘**。

**关键行为**：
- `inspect` 支持 `--json`，便于脚本解析。实测字段：
  `kind`(`pkg`/`folder`/`exfat`/…)、`title_id`、`content_id`、`title_name`、`version`、
  `firmware`、`sdk`（游戏**本来**的要求）、`backport`（降级库文件列表）、`backport_blocked`
  （拒绝 `--remove-backport` 的原因，实测原文：`eboot.bin's SDK 4.00 (0x04000031) is lower than
  param.json's sdkVersion 9.00 (0x09000000); the backport lowered it and the original can't be restored`）、
  `backport_firmware`（**该包被降级到的目标固件**，如 `4.00` —— 判断 fakelib 取舍的核心字段）、
  `emulators`、`dlcs`、`title_names`、`describe`、`forge_version`、
  `files[]`(`path`/`size`)、`empty_dirs`、`total_bytes`、
  `details[]`（含 FIH 布局描述，如 `FIH: debug image, format 3, PFS at 0x10000 (…)`）、
  `param_json`（完整 param.json）、`cover`（base64 PNG 封面）、`lz4`、`archive`。
- `convert` 的进度以 **JSON lines** 输出到 stdout，可据此做进度解析。
- 默认校验是「全部结构检查 + 小文件整文件 + 其余随机抽样」；`--full-verify` 才逐字节重读。
- `-o` 省略时按标题 ID 在源文件旁自动命名。
- `--remove-backport` 会去掉 fakelib 的降级库（保留 AMPR / DLC / PlayGo 模拟器）；
  若 eboot.bin 的 SDK 被下调过，该参数会被拒绝（原因见 `backport_blocked`）。
- `--kraken` 只对 `--to pkg` 生效：`balanced`/`smallest` 体积小约 2.6% 但耗时约 6x / 9x。
- `--level` 只对 `--to ffpfsc` 生效（zlib 级别，默认 6）。

---

## 本机已装的工具（都不适合处理 .pkg）

### exFAT.Image.Builder.exe（kerrdec97 / ps5-exfat-builder）

桌面已有，v4.0.2。GUI。
输入只认 **exfat / ffpkg / ffpfs / ffpfsc**，**不认 `.pkg`**。
用途：在已有镜像格式之间互转、调整几何。

### PS5FpkgBuilderPro.exe

桌面已有。**纯 GUI，无命令行入口**（打包方式里没有 console_scripts / entry_points）。
配置与日志在 `%APPDATA%\PS5FpkgBuilderPro\`（`settings.json`、`logs\session-*.log`）。

### PKGViewer（桌面 `PKGViewer\PKGViewer.exe`）

Tcl/Tk 打包（内嵌 ZipFS，无标准 ZIP 中央目录，拆包价值不大）。
**只会导出 pkg 的元数据**：`param.json`、`icon0/pic0`（dds 与 png）、playgo、奖杯。
遇到 **plaintext(PPRPLAIN-NOAUTH) 外置 PFS** 时会中断，**留下一个只有元数据的空壳目录**。
配置在 `%APPDATA%\PKGViewer\settings.json`。

### PS5PKGTool（pearlxcore，Avalonia GUI）

`github.com/pearlxcore/PS5PKGTool`，v1.3.0 发布包约 90.6 MB。**纯 GUI，无命令行**。
内部含 `LibProsperoPkg.dll`（开源 PS5 PKG 处理库）、`libScePubTools.dll`（官方 PFS/Kraken）、
`oo2core`（Oodle 解压）、Magick.NET（DDS→PNG 转图 —— 空壳目录里的 png 图标就出自它）。
v1.3.0 更新日志声称「extract the PKG's CNT metadata alongside the inner filesystem」，
但它对 plaintext(no-auth) 外置 PFS 依然会只导出元数据后中断。

### OSFMount

挂载镜像用。桌面已装。转换流程用不到，仅用于人工检查镜像内容。

---

## 主机侧访问：etaHEN 内置 ftpsrv

转换之外的工具链成员——直接读写**主机**文件（取日志、看沙箱、传镜像）。

| 项 | 值 |
|---|---|
| 地址 | `<PRIVATE_IP>:2121`（对本用户主机） |
| 认证 | 匿名，用户名/密码留空，被动模式 |
| 封装脚本 | `scripts/ps5ftp.py`（`ls` / `tree` / `cat` / `get` / `put` / `find`） |

**三个必须知道的坑**

1. **透明解密 SELF**：上传 `.sprx` / `.prx` / `.self` / `eboot.bin` 后取回来会变成裸 ELF
   （实测 423,350 B 的 `4f153d1d` → 466,916 B 的 `7f454c46`）。`.elf` 不受影响。
   → **禁止用 FTP 写入签名二进制**；改游戏内容一律走「PC 改目录 → 重打包镜像 → 传镜像」。
2. **`MLSD` 忽略路径参数**，永远返回文件系统根目录 → 必须用 `LIST <path>`。
3. **服务器报的大小/内容不可信** → 传输后必须回传比对（`ps5ftp.py put` 已内置）。

外加一条环境坑：Git Bash 的 MSYS 路径转换会改写 `/data/...`、`/mnt/...` 这类参数
（实测变成 `D:/Program Files/.../PortableGit/mnt/sandbox/...`）→ 先 `export MSYS_NO_PATHCONV=1`。

其它常用位置：`/data/shadowmount/{config.ini,debug.log}`、`/data/homebrew/`、
`/data/etaHEN/games/`、`/mnt/sandbox/PPSAxxxxx_000/`（游戏沙箱）、`/preinst/common/lib`（系统真库）。

---

## 识别「失败空壳」目录

以下特征全部命中，基本可以断定那次转换没跑完、要删掉重来：

- 目录形如 `<标题> - <标题ID> - v<版本> - <区服>/`
- 内部只有：`param.json`、`icon0.dds` / `icon0.png`、`pic0/pic1`、`playgo-chunk.dat`、
  `trophy*.uds` 等**元数据与图片**
- **没有** `eboot.bin`、`sce_sys/`、`sce_module/`、`fakelib/`、`Media/`（即没有游戏本体）

判断方法：看目录里有没有 `eboot.bin`。有才是完整可用的转储。

---

## 常用 GitHub API 速查

```bash
# 最新 release 与资源列表
curl -s https://api.github.com/repos/quer3q/ps5-dump-forge/releases/latest

# 直接下载 CLI 版（把 <ver> 与 <platform> 换成实际值）
curl -sL -o forge.zip \
  https://github.com/quer3q/ps5-dump-forge/releases/download/<ver>/ps5-dump-forge-<ver>-<platform>.zip
```
