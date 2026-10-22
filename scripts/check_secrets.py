#!/usr/bin/env python3
"""Scan repo for secrets / private data. Exit 1 if anything is found.

Usage:
    python scripts/check_secrets.py            # scan tracked-ish files
    python scripts/check_secrets.py --all      # include binary extensions

Allowlist false positives in .secrets-allowlist (one "path:pattern" per line).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv"}
TEXT_EXT = {".md", ".txt", ".py", ".sh", ".json", ".yaml", ".yml", ".ini",
            ".toml", ".cfg", ".conf", ".js", ".ts", ".html", ".css", ".ps1", ".bat"}

CHECKS = [
    # require four full octets, and reject if followed by another digit/version suffix
    ("private-ip", re.compile(
        r"(?<![\d.])(?:192\.168|10)\.\d{1,3}\.\d{1,3}\.\d{1,3}(?![\d.])")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    # 反斜杠在 JSON 里会翻倍，所以要用 `\\{1,2}`，
    # 单反斜杠与转义后的双反斜杠两种写法都要覆盖，否则元数据文件会漏检
    ("abs-user-path", re.compile(
        r"[A-Za-z]:\\{1,2}Users\\{1,2}[A-Za-z0-9_.-]+|/c/Users/[A-Za-z0-9_.-]+|/Users/[A-Za-z0-9_.-]+")),
    ("github-pat", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    # fine-grained PAT 用 github_pat_ 前缀，上面的经典格式正则匹配不到
    ("github-fine-pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}")),
    ("openai-key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("aws-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    # 半角与全角冒号都要覆盖，中文笔记里常见「密码：xxx」
    ("assigned-password", re.compile(
        r"(?i)(?:password|passwd|密码|pwd)\s*[:=：]\s*[\"']?([^\s\"'<>]{6,})")),
]

ALLOWLIST = REPO / ".secrets-allowlist"


def load_allow() -> set[str]:
    if not ALLOWLIST.exists():
        return set()
    return {ln.strip() for ln in ALLOWLIST.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    allow = load_allow()

    findings = []
    for p in REPO.rglob("*"):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if not args.all and p.suffix.lower() not in TEXT_EXT:
            continue
        if p.name == ".secrets-allowlist":
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        rel = p.relative_to(REPO).as_posix()
        for line_no, line in enumerate(text.splitlines(), 1):
            if "<PRIVATE_IP>" in line or "<EMAIL>" in line or "<USER_HOME>" in line:
                # placeholder lines are fine, but still check for leaked real values
                pass
            for name, pat in CHECKS:
                for m in pat.finditer(line):
                    hit = m.group(0)
                    if hit.startswith("<"):
                        continue
                    if f"{rel}:{name}" in allow:
                        continue
                    findings.append((rel, line_no, name, hit[:80]))

    if not findings:
        print("OK: no secrets or private data found")
        return 0

    print(f"FOUND {len(findings)} issue(s):\n")
    for rel, ln, name, hit in findings:
        print(f"  {rel}:{ln}  [{name}]  {hit}")
    print("\nFix: replace with placeholders (<PRIVATE_IP>, <EMAIL>, <PASSWORD>) "
          "or add a justified entry to .secrets-allowlist")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
