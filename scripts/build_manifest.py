#!/usr/bin/env python3
"""Build manifest.json — machine-readable index of skills and notes.

Any AI can read manifest.json first, then open only the entries it needs,
instead of scanning the whole repo.

Usage:
    python scripts/build_manifest.py            # 重新生成 manifest.json
    python scripts/build_manifest.py --check    # 只比对当前 manifest 是否与内容同步

Output schema:
{
  "generated_at": iso8601,
  "counts": {"skills": n, "ideas": n, "decisions": n},
  "skills":   [{name, description, path, has_scripts, has_references, files, bytes, sha256}],
  "ideas":    [{title, slug, path, date, tags, status}],
  "decisions":[...]
}
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def normalize(data: bytes) -> bytes:
    """把 CRLF 归一为 LF 后再取指纹。

    git 会在不同平台做换行转换：Windows 工作区检出为 CRLF，Linux/CI 检出为 LF。
    如果直接对原始字节算 sha256 / 字节数，同一份仓库在 Windows 和 CI 上会得出不同结果，
    「清单是否同步」就永远判为不一致。所以指纹必须基于归一化后的内容。
    """
    return data.replace(b"\r\n", b"\n")


def read_frontmatter(path: Path) -> dict:
    meta: dict = {}
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return meta
    if not text.startswith("---"):
        return meta
    parts = text.split("---", 2)
    if len(parts) < 3:
        return meta
    for line in parts[1].splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k, v = k.strip(), v.strip()
        if not k:
            continue
        if v.startswith("[") and v.endswith("]"):
            meta[k] = [x.strip() for x in v[1:-1].split(",") if x.strip()]
        else:
            meta[k] = v.strip('"').strip("'")
    return meta


def dir_stats(p: Path) -> tuple[int, int]:
    """返回 (文件数, 归一化后的总字节数)。"""
    files = size = 0
    for root, dirs, fs in os.walk(p):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in fs:
            fp = Path(root) / f
            files += 1
            try:
                size += len(normalize(fp.read_bytes()))
            except OSError:
                pass
    return files, size


def digest(path: Path) -> str:
    try:
        return hashlib.sha256(normalize(path.read_bytes())).hexdigest()[:16]
    except OSError:
        return ""


def collect() -> dict:
    """扫描仓库，生成清单（不含写盘副作用）。"""
    skills = []
    skill_root = REPO / "skills"
    if skill_root.is_dir():
        for d in sorted(p for p in skill_root.iterdir() if p.is_dir()):
            md = d / "SKILL.md"
            if not md.exists():
                continue
            meta = read_frontmatter(md)
            files, size = dir_stats(d)
            skills.append({
                "name": meta.get("name", d.name),
                "dir": d.name,
                "description": meta.get("description", ""),
                "path": f"skills/{d.name}/SKILL.md",
                "has_scripts": (d / "scripts").is_dir(),
                "has_references": (d / "references").is_dir(),
                "files": files,
                "bytes": size,
                "sha256": digest(md),
            })

    notes: dict[str, list] = {"ideas": [], "decisions": []}
    for kind in ("ideas", "decisions"):
        base = REPO / "context" / kind
        if not base.is_dir():
            continue
        for p in sorted(base.glob("*.md")):
            if p.name.startswith("_"):
                continue
            meta = read_frontmatter(p)
            notes[kind].append({
                "title": meta.get("title", p.stem),
                "slug": p.stem,
                "path": p.relative_to(REPO).as_posix(),
                "date": meta.get("date", ""),
                "tags": meta.get("tags", []),
                "status": meta.get("status", ""),
            })

    return {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "entry": "AGENTS.md",
        "profile": "context/PROFILE.md",
        "counts": {
            "skills": len(skills),
            "ideas": len(notes["ideas"]),
            "decisions": len(notes["decisions"]),
        },
        "skills": skills,
        "ideas": notes["ideas"],
        "decisions": notes["decisions"],
    }


def check(fresh: dict, out: Path) -> int:
    """比对磁盘上的 manifest.json 是否与仓库内容一致（忽略 generated_at）。"""
    if not out.exists():
        print("manifest.json 不存在，请先运行: python scripts/build_manifest.py")
        return 1
    try:
        old = json.loads(out.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"manifest.json 不是合法 JSON: {e}")
        return 1

    a, b = dict(fresh), dict(old)
    a.pop("generated_at", None)
    b.pop("generated_at", None)
    if a == b:
        print(f"manifest.json 已同步: {fresh['counts']}")
        return 0

    print("manifest.json 与仓库内容不一致：")
    for key in sorted(set(a) | set(b)):
        if a.get(key) == b.get(key):
            continue
        if key == "skills" and isinstance(a.get(key), list) and isinstance(b.get(key), list):
            old_by_dir = {s.get("dir"): s for s in b[key]}
            for s in a[key]:
                o = old_by_dir.get(s.get("dir"))
                if o is None:
                    print(f"  skills: 新增 {s.get('dir')}")
                elif o != s:
                    print(f"  skills: 变动 {s.get('dir')}")
            new_dirs = {s.get("dir") for s in a[key]}
            for d in old_by_dir:
                if d not in new_dirs:
                    print(f"  skills: 已删除 {d}")
        else:
            print(f"  字段 {key}: manifest={str(b.get(key))[:120]} 实际={str(a.get(key))[:120]}")
    print("\n修复: 运行 python scripts/build_manifest.py 后提交 manifest.json")
    return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="生成 / 校验 manifest.json")
    ap.add_argument("--check", action="store_true",
                    help="只比对，不写文件；不一致时返回 1")
    args = ap.parse_args(argv)

    manifest = collect()
    out = REPO / "manifest.json"

    if args.check:
        return check(manifest, out)

    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"manifest.json written: {manifest['counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
