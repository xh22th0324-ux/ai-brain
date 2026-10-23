#!/usr/bin/env python3
"""Export local agent skills into this repo, with sanitization.

Usage:
    python scripts/export_skills.py                 # export all
    python scripts/export_skills.py --only ps5,pptx # export selected
    python scripts/export_skills.py --dry-run       # report only
    python scripts/export_skills.py --src <dir>     # custom source dir

Sanitization replaces private values with placeholders:
    private IPv4      -> <PRIVATE_IP>
    absolute home     -> <USER_HOME>
    agent home path   -> <AGENT_HOME>
    email address     -> <EMAIL>
    extra secrets     -> <REDACTED>   （由环境变量 AI_BRAIN_REDACT 提供，不写进仓库）

Text files only (by extension whitelist); binary files are copied untouched.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_SRC = Path.home() / ".workbuddy" / "skills"
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".idea", ".vscode", ".pytest_cache",
             "test-output", "dist", "build", ".cache", ".venv", "venv"}
# 宿主客户端生成的元数据，对跨模型复用毫无价值，却会带出本机绝对路径
SKIP_FILES = {"_skillhub_meta.json"}
SKIP_EXT = {".pyc", ".pyo", ".zip", ".png", ".jpg", ".jpeg", ".gif", ".webp",
            ".mp4", ".mp3", ".wav", ".pdf", ".xlsx", ".pptx", ".docx", ".ttf",
            ".woff", ".woff2", ".so", ".dll", ".exe", ".bin", ".7z", ".rar"}
TEXT_EXT = {".md", ".txt", ".py", ".sh", ".json", ".yaml", ".yml", ".ini",
            ".toml", ".cfg", ".conf", ".js", ".ts", ".html", ".css", ".ps1", ".bat"}

RULES = [
    (re.compile(r"\b192\.168\.\d{1,3}\.\d{1,3}\b"), "<PRIVATE_IP>"),
    (re.compile(r"\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"), "<PRIVATE_IP>"),
    (re.compile(r"\b172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b"), "<PRIVATE_IP>"),
    # 反斜杠在 JSON / 转义字符串里会翻倍，必须一起吃掉，
    # 否则元数据文件里的绝对路径会原样漏出去。
    (re.compile(r"[A-Za-z]:\\{1,2}Users\\{1,2}[A-Za-z0-9_.-]+"), "<USER_HOME>"),
    (re.compile(r"/c/Users/[A-Za-z0-9_.-]+"), "<USER_HOME>"),
    (re.compile(r"/Users/[A-Za-z0-9_.-]+"), "<USER_HOME>"),
    (re.compile(r"[A-Za-z]:\\{1,2}Users\\{1,2}[A-Za-z0-9_.-]+\\{1,2}\.workbuddy"), "<AGENT_HOME>"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "<EMAIL>"),
]

# 已知的内部凭据**不能写在仓库里**——本仓库是公开的，写进来等于把密码公开。
# 需要额外脱敏时，用环境变量传入（逗号分隔多个）：
#     export AI_BRAIN_REDACT='真实密码1,真实密码2'
_extra = os.environ.get("AI_BRAIN_REDACT", "").strip()
if _extra:
    for _s in (x.strip() for x in _extra.split(",")):
        if len(_s) >= 4:
            RULES.append((re.compile(re.escape(_s)), "<REDACTED>"))


def sanitize(text: str) -> tuple[str, int]:
    hits = 0
    for pat, rep in RULES:
        text, n = pat.subn(rep, text)
        hits += n
    return text, hits


def copy_tree(src: Path, dst: Path, dry: bool) -> tuple[int, int, int]:
    """Returns (files_written, files_skipped, substitutions)."""
    written = skipped = subs = 0
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        rel = Path(root).relative_to(src)
        for name in files:
            s = Path(root) / name
            d = dst / rel / name
            ext = s.suffix.lower()
            if name in SKIP_FILES:
                skipped += 1
                continue
            if ext in SKIP_EXT:
                skipped += 1
                continue
            if ext not in TEXT_EXT:
                skipped += 1
                continue
            try:
                raw = s.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                raw = s.read_text(encoding="gbk", errors="ignore")
            new, n = sanitize(raw)
            subs += n
            if not dry:
                d.parent.mkdir(parents=True, exist_ok=True)
                # 显式 LF：write_text 默认用 os.linesep，Windows 上会写成 CRLF，
                # 与 Linux 的 CI 产出不一致（manifest.json 早先踩过同一个坑）。
                d.write_text(new, encoding="utf-8", newline="\n")
            written += 1
    return written, skipped, subs


def parse_frontmatter(path: Path) -> dict:
    """Minimal YAML frontmatter reader (key: value only)."""
    meta: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return meta
    if not text.startswith("---"):
        return meta
    block = text.split("---", 2)[1] if text.count("---") >= 2 else ""
    for line in block.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(DEFAULT_SRC))
    ap.add_argument("--only", default="", help="comma separated skill names")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    src_root = Path(args.src)
    if not src_root.is_dir():
        print(f"source not found: {src_root}", file=sys.stderr)
        return 2

    wanted = {s.strip() for s in args.only.split(",") if s.strip()}
    dest_root = REPO / "skills"
    dest_root.mkdir(parents=True, exist_ok=True)

    rows = []
    for d in sorted(p for p in src_root.iterdir() if p.is_dir()):
        if wanted and d.name not in wanted:
            continue
        skill_md = d / "SKILL.md"
        if not skill_md.exists():
            print(f"skip (no SKILL.md): {d.name}")
            continue
        meta = parse_frontmatter(skill_md)
        target = dest_root / d.name
        if target.exists() and not args.dry_run:
            shutil.rmtree(target)
        written, skipped, subs = copy_tree(d, target, args.dry_run)
        rows.append((d.name, meta.get("description", "")[:60], written, skipped, subs))
        print(f"{'[dry] ' if args.dry_run else ''}{d.name}: {written} text files, "
              f"{skipped} binary skipped, {subs} substitutions")

    print(f"\n{'DRY RUN — nothing written' if args.dry_run else 'exported'} "
          f"{len(rows)} skills -> {dest_root}")
    print("\nNext: python scripts/build_manifest.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
