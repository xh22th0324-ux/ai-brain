# tools/ — 随包携带的小工具

这里放**拿来就能跑**的独立脚本，和另外两个目录有明确分工：

| 目录 | 是什么 | 谁会用 |
|---|---|---|
| `skills/` | 方法论：怎么做一件事的流程与判断标准 | AI 按流程干活 |
| `scripts/` | 本仓库自身的维护工具（导出技能、生成清单、密钥扫描） | 维护这个仓库的人 |
| `tools/` | 通用小工具：给定输入、产出结果，与仓库本身无关 | 任何需要这个功能的人 |

判断标准很简单：**删掉这个仓库，`tools/` 里的脚本照样有用。**

工具都是纯标准库实现，不需要 `pip install`，Python 3.7+ 直接跑。

---

## zip_each — 批量单独压缩

把目录下的**每个文件各自压成一个独立的压缩包**，原文件不动。

典型场景：一堆散文件要逐个发给别人、逐个上传，或者按文件单独归档。
需要一个总包时**不要**用它，`zip -r` 或 `scripts/make_zip.py` 更合适。

| 文件 | 用途 |
|---|---|
| `zip_each.py` | 主程序，Windows / Linux / macOS / NAS 同一份 |
| `zip_each.bat` | Windows 双击启动器：自动找 Python，跑完停住窗口 |

### 用法

```bash
python zip_each.py                        # 处理脚本所在目录
python zip_each.py D:\照片                 # 指定目录
python zip_each.py /data/new --out /data/packed
python zip_each.py --check                # 只做环境自检（在 NAS 上建议先跑）
python zip_each.py --dry-run              # 只预览会压哪些、跳过哪些
```

Windows 上把两个文件一起放进目标目录，**双击 `zip_each.bat`** 即可。
NAS / Linux 只有 `zip_each.py` 有用，`.bat` 可以忽略。

### 自动跳过规则

**已经压过的文件不会重复压。** 判定依据是目标包的时间戳：

| 情况 | 行为 |
|---|---|
| 目标包不存在 | 压缩 |
| 包存在，且**不比源文件旧** | **跳过** |
| 包存在，但源文件压完之后又被改过（包比源旧） | 重压，避免留下过期包 |
| 包存在但是 0 字节（上次中断的残留） | 补压 |
| 加了 `--overwrite` | 无条件全部重压 |

所以中断后直接重跑即可，已完成的部分会跳过。判定留了 2 秒容差，
兼容 FAT/exFAT 的 2 秒时间精度和 SMB 的秒级取整。

> 若源文件的修改时间在未来（相机时钟错、跨时区拷贝），它每轮都会被判为"比包新"
> 而反复重压。结果不会错，只是白费时间，用 `touch` 校正源文件时间即可。

### 其它行为

- **只处理第一层文件**，不递归子目录
- 目录里已有的 `.zip/.rar/.7z` 默认跳过（避免 `a.zip.zip`），`--include-archives` 可关闭
- 隐藏文件、`Thumbs.db`、`desktop.ini` 跳过
- 已经是压缩格式的（mp4/jpg/mp3/docx…）走**仅存储**模式，不浪费 CPU
- 先写 `.part` 再原子改名，断电或 Ctrl+C 不会留下"看起来完整"的坏包
- 命名默认替换扩展名（`a.mp4 → a.zip`）；去掉扩展名后重名的，改追加模式
  （`photo.jpg → photo.jpg.zip`）以免互相覆盖
- 网络路径（SMB/CIFS/NFS）自动把并发从 8 降到 4

### 在 NAS 上

```bash
python3 zip_each.py --check          # 先自检：Python 版本、文件系统编码、可用工具
python3 zip_each.py /data/new
```

没有 `python3` 时（iStoreOS 精简固件）：`opkg install python3-light`，
或在 Debian / python 容器里跑：

```bash
docker run --rm -v /data:/data python:3.12-slim python /data/new/zip_each.py /data/new
```

`--format rar` 在 iStoreOS 上基本用不了 —— 官方 rarlinux 是 glibc 二进制，
而 iStoreOS 是 musl 环境。用 `--format zip`，或进 Debian 容器。
