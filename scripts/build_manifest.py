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
import ast
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


BLOCK_MARKS = {">", ">-", ">+", "|", "|-", "|+"}


def read_frontmatter(path: Path) -> dict:
    """解析 SKILL.md 的 YAML frontmatter。

    只支持本仓库实际用到的子集，但必须正确处理 YAML 的块标量：
        description: >-        折叠块，多行合并成一行（空格连接）
        description: |         字面块，保留换行
    早先的实现逐行按 ':' 切口，会把 `>-` 本身当成描述，导致索引里
    两个技能的 description 变成 ">-" 和空串 —— 索引也就失去了意义。
    这里不引入 PyYAML，避免给 CI 增加依赖。
    """
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

    lines = parts[1].splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        # 缩进行属于上一个键的块标量，已在上一步消费掉
        if line[0].isspace():
            continue
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k, v = k.strip(), v.strip()
        if not k:
            continue

        if v in BLOCK_MARKS:
            # 收集后续所有比当前键缩进更深的行
            block = []
            while i < len(lines):
                nxt = lines[i]
                if nxt.strip() and not nxt[0].isspace():
                    break
                block.append(nxt.strip())
                i += 1
            joiner = " " if v.startswith(">") else "\n"
            meta[k] = joiner.join(x for x in block if x).strip()
            continue

        if v.startswith("[") and v.endswith("]"):
            meta[k] = [x.strip() for x in v[1:-1].split(",") if x.strip()]
        else:
            meta[k] = v.strip('"').strip("'")
    return meta


def pick_description(meta: dict) -> str:
    """description 缺失时回退到本地化字段，保证索引里没有空描述。"""
    for key in ("description", "description_zh", "description_en"):
        val = meta.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


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


def py_summary(path: Path) -> str:
    """取模块 docstring 的第一行非空文本作为用途摘要。

    用 ast 静态解析，**绝不 import 执行** —— tools/ 下是能直接跑的脚本，
    导入它们会在生成清单时产生副作用。
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, OSError, ValueError):
        return ""
    doc = ast.get_docstring(tree) or ""
    for line in doc.splitlines():
        line = line.strip()
        if line:
            return line
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
                "description": pick_description(meta),
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

    tools = []
    tool_root = REPO / "tools"
    if tool_root.is_dir():
        for p in sorted(tool_root.glob("*.py")):
            if p.name.startswith("_"):
                continue
            # 同 stem 的启动器自动挂到这个工具名下，不硬编码文件名 ——
            # 以后加工具只放文件，这里不用改。
            launchers = sorted(
                q.relative_to(REPO).as_posix()
                for q in tool_root.iterdir()
                if q.is_file() and q.stem == p.stem
                and q.suffix.lower() in {".bat", ".cmd", ".sh", ".ps1"}
            )
            try:
                size = len(normalize(p.read_bytes()))
            except OSError:
                size = 0
            tools.append({
                "name": p.stem,
                "path": p.relative_to(REPO).as_posix(),
                "summary": py_summary(p),
                "launchers": launchers,
                "bytes": size,
                "sha256": digest(p),
            })

    return {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "entry": "AGENTS.md",
        "profile": "context/PROFILE.md",
        "counts": {
            "skills": len(skills),
            "ideas": len(notes["ideas"]),
            "decisions": len(notes["decisions"]),
            "tools": len(tools),
        },
        "skills": skills,
        "tools": tools,
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
        elif key == "tools" and isinstance(a.get(key), list) and isinstance(b.get(key), list):
            old_by_name = {t.get("name"): t for t in b[key]}
            for t in a[key]:
                o = old_by_name.get(t.get("name"))
                if o is None:
                    print(f"  tools: 新增 {t.get('name')}")
                elif o != t:
                    print(f"  tools: 变动 {t.get('name')}（内容或摘要改了）")
            new_names = {t.get("name") for t in a[key]}
            for n in old_by_name:
                if n not in new_names:
                    print(f"  tools: 已删除 {n}")
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

    # 显式 LF：write_text 默认按 os.linesep 写，Windows 会产出 CRLF，
    # 而 CI 在 Linux 上产出 LF —— 同一个文件两边字节数不同，制造假 diff。
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8", newline="\n")
    print(f"manifest.json written: {manifest['counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
