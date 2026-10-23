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

---

## 让别的 AI 用这个工具

压缩这件事最容易被 AI 理解错：它默认会把**所有文件打成一个总包**（`zip -r`），
而这里要的是**每个文件各自一个包**。所以开口时必须说清是哪一种。

### 第一档：它能下载文件（最省事，优先用这个）

> 我有个现成的压缩工具，别自己写。先下载到本地：
>
> ```
> curl -fsSL -o zip_each.py https://raw.githubusercontent.com/xh22th0324-ux/ai-brain/main/tools/zip_each.py
> ```
>
> 这是公开仓库，**不需要任何凭据**。用法：
>
> ```
> python3 zip_each.py <目标目录> --dry-run   # 先给我看计划，别直接压
> python3 zip_each.py <目标目录>             # 我确认后再跑
> ```
>
> 它的作用是：把目标目录**第一层**的每个文件**各自**压成一个独立压缩包
> （`a.txt → a.zip`、`b.mp4 → b.zip`），**原文件一个字节都不改**；
> 已经压过且源文件没变的会自动跳过。
> 详细行为见同目录 `README.md`。

### 第二档：它是本地 CLI（Codex CLI / Gemini CLI / Cursor 等）

> 执行 `git clone --depth 1 https://github.com/xh22th0324-ux/ai-brain`，
> 脚本在 `tools/zip_each.py`，`tools/README.md` 是它的说明。公开仓库，无需凭据。
> 只读，不要往仓库里推任何东西。

### 第三档：它拿不到文件，只能按描述自己写

这时才让它写，但要给足约束 —— 少一条就容易出一个"看起来能用、实际会丢数据"的版本：

> 写一个脚本实现「把目录下每个文件各自压成一个独立包」，**必须满足**：
>
> 1. 只处理目录**第一层**，不递归子目录
> 2. 命名用「原文件名去掉扩展名 + `.zip`」（`a.txt → a.zip`）；
>    两个文件去掉扩展名后重名时改成追加形式（`photo.jpg → photo.jpg.zip`），别互相覆盖
> 3. **原文件绝对不删、不改、不移动**
> 4. **目标包已存在且不比源文件旧就跳过**；包比源文件旧说明源改过，要重压。
>    时间比较留 2 秒容差（FAT/exFAT 的精度就是 2 秒）
> 5. 先写 `<包名>.part`，写完再原子改名，中断时不能留下"看起来完整"的坏包
> 6. 中文文件名要正常，路径里有空格要能处理
> 7. 已经压过的源文件（`.zip/.rar/.7z`）默认跳过，否则会出现 `a.zip.zip`
>
> 写完先 `--dry-run` 给我看计划，我确认后再跑。

### 别这么说（实测会被理解错）

| 说法 | 它通常会怎么做 | 问题 |
|---|---|---|
| "帮我压缩一下这些文件" | `zip -r all.zip .` 打成一个总包 | 完全不是要的东西 |
| "每个文件单独压" （不说清落点） | 压成 `a.txt.zip`，多一层扩展名 | 你要的是 `a.zip` |
| 不说目标目录 | 按它自己的 cwd 压 | 压错目录，还可能压到仓库里 |
| "顺便把源文件删掉" | 删了 | 这里不该有删除动作，压缩是只读的 |

**一句话记法**：说「每个文件**各自一个包**」，并强调「**原文件不动**」。

