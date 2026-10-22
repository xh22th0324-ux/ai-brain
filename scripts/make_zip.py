#!/usr/bin/env python3
"""把仓库打包成可直接上传给对话式 AI 的 zip。

为什么要这个脚本：
    每次改完内容手动「右键压缩」容易忘、容易把 .git 一起打进去（体积翻几倍），
    也容易漏掉新文件。跑一条命令，结果可重复。

用法:
    python scripts/make_zip.py                     # 输出 ../ai-brain-YYYYMMDD.zip
    python scripts/make_zip.py -o D:/x/a.zip       # 指定输出路径
    python scripts/make_zip.py --list              # 只列出会打包哪些文件

约定:
    - 排除 .git / 缓存 / 虚拟环境 / 本脚本产物
    - zip 里所有条目统一以 ai-brain/ 为根目录，解压后不会散落一地
    - 打包前强制跑一次密钥扫描，扫描不过就不出包
"""
from __future__ import annotations

import argparse
import sys
import zipfile
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ROOT_IN_ZIP = "ai-brain"

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv",
             "dist", "build", ".cache", ".pytest_cache", ".idea", ".vscode"}
SKIP_SUFFIX = {".pyc", ".pyo"}


def iter_files(base: Path):
    """按稳定顺序产出 (绝对路径, 相对路径)。"""
    for p in sorted(base.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(base)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if p.suffix.lower() in SKIP_SUFFIX:
            continue
        if p.name.startswith(".DS_Store"):
            continue
        yield p, rel


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="打包 ai-brain 为可上传的 zip")
    ap.add_argument("-o", "--out", default="", help="输出 zip 路径")
    ap.add_argument("--list", action="store_true", help="只列出文件，不打包")
    args = ap.parse_args(argv)

    # 出包前先做密钥体检，宁可不出包也不要漏东西
    if not args.list:
        sys.path.insert(0, str(REPO / "scripts"))
        try:
            import check_secrets
        except Exception as e:                       # noqa: BLE001
            print(f"无法加载 check_secrets: {e}", file=sys.stderr)
            return 2
        if check_secrets.main() != 0:
            print("\n密钥扫描未通过，已中止打包。先修掉上面列出的问题。", file=sys.stderr)
            return 1
        print()

    files = list(iter_files(REPO))
    if args.list:
        for _, rel in files:
            print(rel.as_posix())
        print(f"\n共 {len(files)} 个文件")
        return 0

    out = Path(args.out) if args.out else REPO.parent / f"ai-brain-{date.today():%Y%m%d}.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()

    total = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for src, rel in files:
            zf.write(src, f"{ROOT_IN_ZIP}/{rel.as_posix()}")
            total += src.stat().st_size

    size = out.stat().st_size
    print(f"已生成: {out}")
    print(f"文件数: {len(files)}   原始 {total/1048576:.2f} MB   压缩后 {size/1048576:.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
