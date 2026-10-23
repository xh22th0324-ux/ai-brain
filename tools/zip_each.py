#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量单独压缩：指定目录下的每个文件，各自压成一个独立的压缩包。

跨平台：Windows / Linux / macOS 同一份代码，也可直接对 NAS 共享目录运行。
Python 3.7+ 即可，无第三方依赖。

用法
----
    python zip_each.py                       # 处理脚本所在目录
    python zip_each.py D:\\照片               # 指定目录
    python zip_each.py /volume1/photo        # Linux / NAS 本地路径
    python zip_each.py "\\\\iStoreOS\\新片"   # Windows 访问 NAS 共享
    python zip_each.py /data/new --out /data/packed
    python zip_each.py --check               # 先做环境自检（在 NAS 上建议先跑这个）
    python zip_each.py --dry-run             # 只预览，不压缩

设计要点
--------
* 只处理目录**第一层**的文件，不递归子目录（避免同名冲突与意外扩大范围）
* 已是压缩格式的文件（mp4/jpg/mp3/zip…）自动用「仅存储」模式：
  解压后字节完全一致，速度快数倍，不会把 CPU 白白烧掉
* 断点续跑 / 自动跳过：包已存在且**不比源文件旧**就跳过；
  源文件压完之后又被改过的（包比源旧），会自动重压，不会留过期包。
  判定留 2 秒容差以兼容 FAT/exFAT 与 SMB 的时间精度
* 先写 `.part` 临时文件，成功后原子改名：断电或 Ctrl+C 不会留下"看起来完整"的坏包
* 命名默认替换扩展名（`a.mp4 → a.zip`）；若两个文件去掉扩展名后同名，
  自动改为追加模式（`a.mp4.zip`）以免互相覆盖
* 网络路径（SMB/CIFS/NFS）自动降低并发，避免把链路压垮
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# ---------------------------------------------------------------- 配置

# 这些扩展名本身已是压缩容器，再 deflate 几乎不减小，纯属浪费 CPU。
STORE_EXT = {
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".ts", ".m2ts",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".bmp", ".tif", ".tiff",
    ".mp3", ".flac", ".aac", ".m4a", ".wav", ".ogg", ".opus",
    ".zip", ".rar", ".7z", ".gz", ".bz2", ".xz", ".zst", ".cab",
    ".apk", ".ipa", ".iso", ".pkg", ".docx", ".xlsx", ".pptx",
}

# 系统垃圾文件，压了也没意义
IGNORE_NAMES = {"thumbs.db", "desktop.ini", ".ds_store", "ehthumbs.db"}

FORMAT_EXT = {"zip": ".zip", "rar": ".rar", "7z": ".7z"}

# 脚本自身的伴生文件（启动器、说明）不应被打包成 xxx.zip。
# 只按「与脚本同 stem」匹配，不做模糊猜测，避免误伤用户数据。
SELF_PATH = Path(__file__).resolve()
SELF_STRICT = {SELF_PATH.name.lower()} | {
    SELF_PATH.stem.lower() + ext for ext in (".bat", ".cmd", ".sh", ".ps1", ".md")
}

# 外部工具在 Linux / NAS 上的常见位置（PATH 里找不到时兜底）
TOOL_CANDIDATES = {
    "rar": ["/usr/bin/rar", "/usr/local/bin/rar", "/opt/rar/rar", "/opt/rar/rar.exe"],
    "7z": ["/usr/bin/7z", "/usr/bin/7zz", "/usr/local/bin/7z",
           "/usr/lib/p7zip/7z", "/opt/homebrew/bin/7z"],
}

NET_FS = {"cifs", "smb3", "smbfs", "nfs", "nfs4", "fuse.sshfs", "fuseblk", "davfs"}


# ---------------------------------------------------------------- 跨平台小工具

def decode_out(b: bytes) -> str:
    """外部程序输出的解码：Linux 多为 UTF-8，Windows 版 Rar 输出 GBK。"""
    if not b:
        return ""
    for enc in ("utf-8", "gbk", "cp936"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", "replace")


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def human_time(sec: float) -> str:
    if sec < 60:
        return f"{sec:.1f}s"
    m, s = divmod(int(sec), 60)
    if m < 60:
        return f"{m}m{s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m"


def safe_size(p: Path) -> int:
    """网络盘上单个文件 stat 可能临时失败，失败按 0 处理，不中断整体流程。"""
    try:
        return p.stat().st_size
    except OSError:
        return 0


def free_space(path: Path) -> int:
    """目标所在卷可用字节；网络路径取不到时返回 0（表示未知）。"""
    p = path
    while not p.exists() and p.parent != p:
        p = p.parent
    try:
        return shutil.disk_usage(str(p)).free
    except OSError:
        return 0


def _unescape_mount(s: str) -> str:
    """ /proc/mounts 里的空格等字符会被转义成 \\040 形式。"""
    return (s.replace("\\040", " ").replace("\\011", "\t")
             .replace("\\012", "\n").replace("\\134", "\\"))


def is_network_path(p: Path) -> bool:
    """判断路径是否落在网络文件系统上。"""
    s = str(p)
    if s.startswith("\\\\") or s.startswith("//"):     # Windows UNC
        return True
    if sys.platform == "win32":
        return False
    try:
        with open("/proc/mounts", encoding="utf-8", errors="ignore") as f:
            mounts = []
            for line in f:
                parts = line.split()
                if len(parts) >= 3:
                    mounts.append((_unescape_mount(parts[1]), parts[2]))
        mounts.sort(key=lambda m: -len(m[0]))           # 最长挂载点优先
        for mnt, fstype in mounts:
            if mnt != "/" and s.startswith(mnt):
                return fstype in NET_FS
    except OSError:
        pass
    return False


def find_tool() -> dict[str, str]:
    """探测可用的外部压缩工具，PATH 找不到时按常见安装位置兜底。"""
    found: dict[str, str] = {}
    for name in ("rar", "7z", "7zz"):
        p = shutil.which(name)
        if p:
            key = "7z" if name.startswith("7z") else "rar"
            found.setdefault(key, p)
    for key, cands in TOOL_CANDIDATES.items():
        if key in found:
            continue
        for c in cands:
            if Path(c).is_file():
                found[key] = c
                break
    # Windows 标准安装位置
    for cand in (r"C:\Program Files\WinRAR\Rar.exe",
                 r"C:\Program Files (x86)\WinRAR\Rar.exe",
                 r"C:\Program Files\7-Zip\7z.exe"):
        if Path(cand).is_file():
            found.setdefault("rar" if "WinRAR" in cand else "7z", cand)
    return found


def check_env(root: Path, out_dir: Path) -> None:
    """环境自检：在 NAS 上先跑这个，能立刻看出缺什么。"""
    fsenc = sys.getfilesystemencoding()
    ioenc = (getattr(sys.stdout, "encoding", None) or "?").lower()
    tools = find_tool()
    net = is_network_path(root)
    free = free_space(out_dir)

    print("环境自检")
    print(f"  Python        : {sys.version.split()[0]}  ({sys.implementation.name})")
    print(f"  平台          : {sys.platform}  ({os.name})")
    print(f"  文件系统编码  : {fsenc}   {'OK' if fsenc.lower() in ('utf-8','utf8','mbcs') else '⚠ 可能无法正确处理中文文件名'}")
    print(f"  终端输出编码  : {ioenc}")
    print(f"  压缩工具      : rar={tools.get('rar') or '无'}  7z={tools.get('7z') or '无'}")
    print(f"  目标路径      : {root}")
    print(f"  路径类型      : {'网络（SMB/NFS）' if net else '本地'}")
    print(f"  可用空间      : {human(free) if free else '未知（网络路径可能取不到）'}")
    print(f"  建议并发      : {4 if net else min(8, os.cpu_count() or 4)}")

    warn = []
    if fsenc.lower() == "ascii":
        warn.append("文件系统编码是 ascii，中文文件名会出错。启动前设 PYTHONUTF8=1 或 LANG=C.UTF-8")
    if net and free == 0:
        warn.append("网络路径取不到可用空间，脚本不会做空间预警，请自行留意")
    if sys.platform != "win32" and "rar" not in tools:
        warn.append("未找到 rar：iStoreOS/OpenWrt 基于 musl，官方 rarlinux 是 glibc 二进制，"
                    "直接跑会报 Permission denied 或 No such file。请用 --format zip，"
                    "或在 Debian 容器内运行")
    print()
    if warn:
        for w in warn:
            print(f"  ⚠ {w}")
    else:
        print("  未发现明显问题，可以正常使用。")


# ---------------------------------------------------------------- 打包实现

def pack_zip(src: Path, dst_tmp: Path, level: int) -> None:
    ext = src.suffix.lower()
    if ext in STORE_EXT:
        comp, lvl = zipfile.ZIP_STORED, None
    else:
        comp, lvl = zipfile.ZIP_DEFLATED, level

    with zipfile.ZipFile(dst_tmp, "w", compression=comp,
                         compresslevel=lvl, allowZip64=True) as z:
        z.write(src, arcname=src.name)


def pack_rar(src: Path, dst_tmp: Path, rar_exe: str) -> None:
    """-ep 不保存路径，-m0 仅存储，-m3 标准压缩。"""
    mode = "-m0" if src.suffix.lower() in STORE_EXT else "-m3"
    if dst_tmp.exists():
        dst_tmp.unlink()
    r = subprocess.run(
        [rar_exe, "a", mode, "-ep", "-idq", "-y", str(dst_tmp), str(src)],
        capture_output=True,
    )
    if r.returncode != 0:
        msg = decode_out(r.stdout).strip() or decode_out(r.stderr).strip()
        raise RuntimeError(msg or f"Rar 退出码 {r.returncode}")


def pack_7z(src: Path, dst_tmp: Path, exe: str) -> None:
    mode = "-mx0" if src.suffix.lower() in STORE_EXT else "-mx5"
    if dst_tmp.exists():
        dst_tmp.unlink()
    r = subprocess.run(
        [exe, "a", mode, "-y", str(dst_tmp), str(src)],
        capture_output=True,
    )
    if r.returncode != 0:
        msg = decode_out(r.stdout).strip() or decode_out(r.stderr).strip()
        raise RuntimeError(msg or f"7z 退出码 {r.returncode}")


def verify_zip(path: Path) -> None:
    with zipfile.ZipFile(path) as z:
        bad = z.testzip()
        if bad is not None:
            raise RuntimeError(f"包内文件校验失败: {bad}")


# ---------------------------------------------------------------- 主流程

def build_jobs(files: list[Path], out_dir: Path, fmt: str):
    """决定每个源文件对应的目标包路径，处理同名冲突。"""
    ext = FORMAT_EXT[fmt]
    stems: dict[str, int] = {}
    for f in files:
        stems[f.stem] = stems.get(f.stem, 0) + 1

    jobs = []
    for f in files:
        if stems[f.stem] == 1:
            name = f.stem + ext
        else:
            name = f.name + ext
        jobs.append((f, out_dir / name))
    return jobs


def plan_rebuild(src: Path, dst: Path, overwrite: bool) -> str:
    """判断一个源文件该压还是该跳。返回原因代码：

    overwrite  指定了 --overwrite，无条件重压
    new        目标包不存在
    empty      目标包存在但是 0 字节（上次中断留下的坏包）
    stale      包比源旧 —— 源文件压完之后又被改过，包已过期
    unchanged  包比源新，内容视为没有变化，跳过
    """
    if overwrite:
        return "overwrite"
    if not dst.exists():
        return "new"
    if safe_size(dst) <= 0:
        return "empty"
    try:
        src_m = src.stat().st_mtime
        dst_m = dst.stat().st_mtime
    except OSError:
        # 网络盘 stat 抖动时宁可跳过，下一轮还会再判一次
        return "unchanged"
    # 容差 2 秒：FAT/exFAT 的 mtime 精度就是 2 秒，SMB 还可能有秒级取整。
    # 方向刻意偏"多压一次"—— 重压无损，留个过期包才是真问题。
    if src_m > dst_m + 2:
        return "stale"
    return "unchanged"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="把目录下每个文件单独压成一个压缩包（原文件不动）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("dir", nargs="?", default=None, help="要处理的目录，默认脚本所在目录")
    ap.add_argument("--out", default=None, help="压缩包输出目录，默认与原文件同目录")
    ap.add_argument("--format", choices=["zip", "rar", "7z"], default="zip", help="压缩格式")
    ap.add_argument("--level", type=int, default=6, help="zip 压缩级别 1-9")
    ap.add_argument("--jobs", type=int, default=None, help="并行线程数，默认本地 8、网络 4")
    ap.add_argument("--overwrite", action="store_true",
                    help="无条件重压全部（默认：包不存在、或比源文件旧，才压）")
    ap.add_argument("--verify", action="store_true", help="打包后校验完整性（慢约 20%）")
    ap.add_argument("--include-archives", action="store_true",
                    help="把已有的压缩包也再压一层（默认跳过，避免 a.zip.zip）")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不实际压缩")
    ap.add_argument("--check", action="store_true", help="只做环境自检后退出")
    ap.add_argument("--pause", action="store_true", help="结束后暂停（双击运行时用）")
    args = ap.parse_args()

    root = Path(args.dir).expanduser() if args.dir else Path(__file__).resolve().parent
    try:
        root = root.resolve()
    except OSError:
        pass
    if not root.is_dir():
        print(f"目录不存在或不可访问: {root}", file=sys.stderr)
        return 2

    out_dir = (Path(args.out).expanduser() if args.out else root)
    try:
        out_dir = out_dir.resolve()
    except OSError:
        pass

    if args.check:
        check_env(root, out_dir)
        return 0

    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"无法创建输出目录 {out_dir}: {e}", file=sys.stderr)
        return 2

    # ---- 工具与并发决策 ----
    tools = find_tool()
    if args.format == "rar" and "rar" not in tools:
        print("未找到 rar。\n"
              "  Windows：安装 WinRAR\n"
              "  Linux/NAS：iStoreOS 是 musl 环境，官方 rarlinux 是 glibc 二进制，直接跑会失败；\n"
              "             请改用 --format zip，或在 Debian 容器内运行。", file=sys.stderr)
        return 2
    if args.format == "7z" and "7z" not in tools:
        print("未找到 7z。安装 7-Zip（Linux: apt install p7zip-full）后重试，或改用 --format zip",
              file=sys.stderr)
        return 2

    net = is_network_path(root) or is_network_path(out_dir)
    jobs_n = args.jobs if args.jobs else (4 if net else min(8, os.cpu_count() or 4))

    # ---- 收集文件 ----
    try:
        entries = list(root.iterdir())
    except OSError as e:
        print(f"无法列出目录 {root}: {e}", file=sys.stderr)
        return 2

    files, skipped_archives = [], []
    for p in entries:
        try:
            if not p.is_file():
                continue
        except OSError:
            continue
        if p.name.startswith(".") or p.name.lower() in IGNORE_NAMES:
            continue
        if p.name.endswith(".part"):
            continue
        if p.name.lower() in SELF_STRICT:
            continue
        try:
            if p.resolve() == SELF_PATH:
                continue
        except OSError:
            pass
        if not args.include_archives and p.suffix.lower() in FORMAT_EXT.values():
            skipped_archives.append(p)
            continue
        files.append(p)
    files.sort(key=lambda x: x.name.lower())

    if not files:
        print(f"目录里没有可处理的文件: {root}")
        if skipped_archives:
            print(f"（跳过了 {len(skipped_archives)} 个已有压缩包，加 --include-archives 可一并处理）")
        return 1

    jobs = build_jobs(files, out_dir, args.format)

    # ---- 跳过策略：包已存在且不比源旧，就认为压过了 ----
    pending, skipped, restale = [], 0, 0
    for src, dst in jobs:
        why = plan_rebuild(src, dst, args.overwrite)
        if why == "unchanged":
            skipped += 1
        else:
            if why == "stale":
                restale += 1
            pending.append((src, dst))

    src_total = sum(safe_size(s) for s, _ in jobs)
    free = free_space(out_dir)

    print(f"目录      : {root}")
    print(f"输出      : {out_dir}")
    print(f"格式      : {args.format.upper()}")
    print(f"路径类型  : {'网络' if net else '本地'}")
    print(f"文件数    : {len(jobs)}   待压缩 {len(pending)}   跳过 {skipped}"
          + (f"（其中源已更新 {restale} 个会重压）" if restale else "")
          + (f"   略过压缩包 {len(skipped_archives)}" if skipped_archives else ""))
    print(f"源总大小  : {human(src_total)}")
    print(f"目标可用  : {human(free) if free else '未知'}")
    print(f"并行线程  : {jobs_n}")
    if sys.getfilesystemencoding().lower() == "ascii":
        print("警告      : 文件系统编码为 ascii，中文文件名可能出错，建议 PYTHONUTF8=1 重跑")
    print()

    if free and pending and free < src_total * 0.5:
        print("警告：目标盘可用空间可能不足（按源体积的一半估算）。确认后再继续。\n")

    if args.dry_run:
        print("—— 预览模式，不实际压缩 ——")
        TAG = {"unchanged": "跳过", "stale": "重压", "new": "压缩",
               "empty": "补压", "overwrite": "重压"}
        for src, dst in jobs:
            tag = TAG[plan_rebuild(src, dst, args.overwrite)]
            est = "存储" if src.suffix.lower() in STORE_EXT else "deflate"
            print(f"  [{tag}] {src.name}  →  {dst.name}   ({human(safe_size(src))}, {est})")
        return 0

    ok, fail = 0, 0              # 成功只算本轮真正压出来的，跳过的单独计数，避免「待压1 成功3」的自相矛盾
    packed_bytes = 0            # 只统计本轮真正压缩的字节，跳过的计入会让均速失真
    t0 = time.time()

    def work(src: Path, dst: Path):
        tmp = dst.with_name(dst.name + ".part")
        try:
            if args.format == "zip":
                pack_zip(src, tmp, args.level)
            elif args.format == "rar":
                pack_rar(src, tmp, tools["rar"])
            else:
                pack_7z(src, tmp, tools["7z"])
            if args.format == "zip" and args.verify:
                verify_zip(tmp)
            os.replace(tmp, dst)          # 同目录内原子改写，失败不会留坏包
            return src, dst, None
        except Exception as e:            # noqa: BLE001
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
            return src, dst, e

    total = len(pending)
    with ThreadPoolExecutor(max_workers=max(1, jobs_n)) as pool:
        futs = {pool.submit(work, s, d): (s, d) for s, d in pending}
        for i, fut in enumerate(as_completed(futs), 1):
            src, dst, err = fut.result()
            size = safe_size(src)
            if err:
                fail += 1
                print(f"[{i}/{total}] 失败  {src.name}\n         {err}")
            else:
                ok += 1
                packed_bytes += size
                got = safe_size(dst)
                ratio = (got / size * 100) if size else 0
                print(f"[{i}/{total}] OK    {src.name}  {human(size)} → {human(got)} ({ratio:.0f}%)")

    elapsed = time.time() - t0
    speed = (packed_bytes / elapsed / 1024 / 1024) if elapsed > 0.05 else 0

    print()
    print("=" * 56)
    print(f"成功 {ok}   失败 {fail}   跳过 {skipped}   用时 {human_time(elapsed)}"
          f"   均速 {speed:.1f} MB/s")

    out_total = sum(safe_size(d) for _, d in jobs)
    print(f"输出总量 {human(out_total)}（源 {human(src_total)}）")
    print("原文件未做任何改动。")
    return 1 if fail else 0


if __name__ == "__main__":
    code = main()
    if code == 0 and "--pause" in sys.argv:
        input("按回车退出...")
    sys.exit(code)
