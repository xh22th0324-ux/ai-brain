#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""self-tune — 本机 WorkBuddy / Windows 环境体检与自动调参。

用法：
    python self_tune.py check                 # 只读体检（默认）
    python self_tune.py check --json
    python self_tune.py check --only temp_dir,local_skills_memory
    python self_tune.py apply --yes           # 真改；不带 --yes 只打印计划

退出码：0 全部符合 / 1 有差异 / 2 执行错误
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import unicodedata
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
EXPECTED_FILE = SKILL_DIR / "config" / "expected.json"

ROOT = Path(os.environ.get("WORKBUDDY_HOME") or (Path.home() / ".workbuddy"))
APP_CONFIG = ROOT / "app" / "app-config.json"
SETTINGS = ROOT / "settings.json"
SKILLS_DIR = ROOT / "skills"
BACKUP_DIR = ROOT / "tools" / "self_tune_backups"
LOG_FILE = ROOT / "tools" / "self_tune_log.jsonl"

FIX_HINT = "退出 WorkBuddy 后重启才生效"


# ---------------------------------------------------------------- 基础工具


def dwidth(s: str) -> int:
    """中文按 2 列宽计算，保证表格对齐。"""
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in str(s))


def pad(s, width: int) -> str:
    s = str(s)
    return s + " " * max(0, width - dwidth(s))


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        return {}
    return json.loads(raw)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".selftune.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


_RUN_STAMP = time.strftime("%Y%m%d-%H%M%S")
_BACKED_UP: dict[Path, Path] = {}


def backup(path: Path) -> Path | None:
    """同一轮 apply 内每个文件只备份一次（保留改动前的原始状态）。"""
    if path in _BACKED_UP:
        return _BACKED_UP[path]
    if not path.exists():
        return None
    dest_dir = BACKUP_DIR / _RUN_STAMP
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / path.name
    shutil.copy2(path, dest)
    _BACKED_UP[path] = dest
    return dest


def log(entry: dict) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **entry}
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def dotted_set(obj: dict, dotted: str, value) -> None:
    parts = dotted.split(".")
    for p in parts[:-1]:
        obj = obj.setdefault(p, {})
        if not isinstance(obj, dict):
            raise ValueError(f"路径 {dotted} 中途不是对象")
    obj[parts[-1]] = value


def dotted_get(obj: dict, dotted: str, default=None):
    cur = obj
    for p in dotted.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return cur


# ---------------------------------------------------------------- 注册表（环境变量）


def env_temp_values() -> tuple[str | None, str | None]:
    try:
        import winreg
    except ImportError:
        return (os.environ.get("TEMP"), os.environ.get("TMP"))
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            def get(name):
                try:
                    return winreg.QueryValueEx(key, name)[0]
                except FileNotFoundError:
                    return None
            return (get("TEMP"), get("TMP"))
    except OSError:
        return (os.environ.get("TEMP"), os.environ.get("TMP"))


def set_user_env(names: list[str], value: str) -> None:
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
        for n in names:
            winreg.SetValueEx(key, n, 0, winreg.REG_EXPAND_SZ, value)
    # 广播 WM_SETTINGCHANGE，让新开的进程立刻拿到新值
    try:
        import ctypes
        HWND_BROADCAST, WM_SETTINGCHANGE, SMTO_ABORTIFHUNG = 0xFFFF, 0x001A, 0x0002
        res = ctypes.c_ulong()
        ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment",
            SMTO_ABORTIFHUNG, 5000, ctypes.byref(res),
        )
    except Exception:
        pass


# ---------------------------------------------------------------- 清单项


class Item:
    key: str
    label: str

    def __init__(self, key, label, current, expected, detail, apply_fn=None, note=""):
        self.key = key
        self.label = label
        self.current = current
        self.expected = expected
        self.detail = detail
        self.apply_fn = apply_fn
        self.note = note

    @property
    def fixable(self) -> bool:
        return self.apply_fn is not None

    @property
    def ok(self) -> bool:
        if self.expected is None:
            return True  # null = 不判定
        return self.current == self.expected

    def as_dict(self):
        return {
            "key": self.key,
            "label": self.label,
            "current": self.current,
            "expected": self.expected,
            "ok": self.ok,
            "fixable": self.fixable,
            "detail": self.detail,
            "note": self.note,
        }


def build_items(expected: dict) -> list[Item]:
    items: list[Item] = []
    app = read_json(APP_CONFIG)
    settings = read_json(SETTINGS)

    # 1. 临时目录
    t_val, t_tmp = env_temp_values()
    want_temp = expected.get("temp_dir")

    def fix_temp():
        set_user_env(["TEMP", "TMP"], want_temp)
        Path(want_temp).mkdir(parents=True, exist_ok=True)

    items.append(Item(
        "temp_dir", "临时目录",
        current=t_val if t_val == t_tmp else f"TEMP={t_val} / TMP={t_tmp}",
        expected=want_temp,
        detail=f"注册表 HKCU\\Environment；当前进程仍为 {os.environ.get('TEMP')}",
        apply_fn=fix_temp if want_temp else None,
        note=FIX_HINT,
    ))

    # 2. 本地技能与记忆沉淀（app-config，存的是「禁用」）
    cur_lsm = not bool(app.get("disableLocalSkillsMemory", False))
    want_lsm = expected.get("local_skills_memory")

    def fix_lsm():
        def mut(d):
            d["disableLocalSkillsMemory"] = not bool(want_lsm)
        apply_to_file(APP_CONFIG, mut, "local_skills_memory", cur_lsm, want_lsm)

    items.append(Item(
        "local_skills_memory", "本地技能与记忆沉淀",
        current=cur_lsm, expected=want_lsm,
        detail=f"{APP_CONFIG.name}:disableLocalSkillsMemory={app.get('disableLocalSkillsMemory', '(未设)')}",
        apply_fn=fix_lsm if want_lsm is not None else None,
        note="存的是「禁用」布尔值，false 才是开",
    ))

    # 3. 记忆生成（settings.json）
    cur_gen = settings.get("generateMemoryEnabled", True)
    want_gen = expected.get("memory_generate")

    def fix_gen():
        def mut(d):
            d["generateMemoryEnabled"] = bool(want_gen)
        apply_to_file(SETTINGS, mut, "memory_generate", cur_gen, want_gen)

    items.append(Item(
        "memory_generate", "记忆生成（云端）",
        current=cur_gen, expected=want_gen,
        detail=f"settings.json:generateMemoryEnabled={settings.get('generateMemoryEnabled', '(未设=开)')}",
        apply_fn=fix_gen if want_gen is not None else None,
    ))

    # 4. 本地记忆（settings.json）
    cur_loc = settings.get("localMemoryEnabled", False)
    want_loc = expected.get("local_memory")

    def fix_loc():
        def mut(d):
            d["localMemoryEnabled"] = bool(want_loc)
        apply_to_file(SETTINGS, mut, "local_memory", cur_loc, want_loc)

    items.append(Item(
        "local_memory", "本地记忆",
        current=cur_loc, expected=want_loc,
        detail=f"settings.json:localMemoryEnabled={settings.get('localMemoryEnabled', '(未设=关)')}",
        apply_fn=fix_loc if want_loc is not None else None,
        note="清单里 null = 只报告不改",
    ))

    # 5~9. app-config 内的普通字段
    app_fields = [
        ("default_workspace", "默认工作区", "defaultWorkspacePath"),
        ("locale", "界面语言", "locale"),
        ("tone_style", "语气风格", "personalization.toneStyle"),
        ("sandbox_safety", "沙箱安全", "sandboxSafetyEnabled"),
    ]
    defaults = {"sandbox_safety": True}
    for key, label, path in app_fields:
        cur = dotted_get(app, path, defaults.get(key))
        want = expected.get(key)

        def fix(path=path, want=want, key=key, cur=cur):
            def mut(d):
                dotted_set(d, path, want)
            apply_to_file(APP_CONFIG, mut, key, cur, want)

        items.append(Item(key, label, current=cur, expected=want,
                          detail=f"app-config.json:{path}",
                          apply_fn=fix if want is not None else None))

    # Agent Teams（存的是「禁用」）
    cur_team = not bool(app.get("disableAgentTeams", False))
    want_team = expected.get("agent_teams")

    def fix_team():
        def mut(d):
            d["disableAgentTeams"] = not bool(want_team)
        apply_to_file(APP_CONFIG, mut, "agent_teams", cur_team, want_team)

    items.append(Item("agent_teams", "多 Agent 协作",
                      current=cur_team, expected=want_team,
                      detail=f"app-config.json:disableAgentTeams={app.get('disableAgentTeams', '(未设)')}",
                      apply_fn=fix_team if want_team is not None else None,
                      note="存的是「禁用」布尔值"))

    # 10. 本地技能目录（只检查）
    n_skills = 0
    if SKILLS_DIR.exists():
        n_skills = sum(1 for d in SKILLS_DIR.iterdir()
                       if d.is_dir() and (d / "SKILL.md").exists())
    items.append(Item("skills_dir", "本地技能目录",
                      current=f"{n_skills} 个技能", expected=None,
                      detail=str(SKILLS_DIR)))

    # 11. 技能归档共享（只探测）
    share = expected.get("skills_archive")
    reach = "未配置"
    if share:
        try:
            reach = "可达" if any(Path(share).iterdir()) or Path(share).exists() else "不可达"
        except OSError:
            reach = "不可达"
    items.append(Item("skills_archive", "技能归档共享",
                      current=reach, expected=None,
                      detail=str(share or "-")))

    return items


# ---------------------------------------------------------------- 写入


def apply_to_file(path: Path, mutate, key: str, before, after) -> None:
    data = read_json(path)
    mutate(data)
    bak = backup(path)
    write_json(path, data)
    log({"action": "apply", "key": key, "file": str(path),
         "before": before, "after": after, "backup": str(bak) if bak else None})


# ---------------------------------------------------------------- 输出


def render(items: list[Item], do_apply: bool) -> None:
    bad = [i for i in items if not i.ok]
    print()
    if not bad:
        print("结论：全部符合预期，不用动。")
    else:
        print(f"结论：{len(items)} 项里 {len(bad)} 项不符合预期。")
    print()
    print(pad("项目", 24) + pad("当前值", 26) + pad("期望值", 26) + "状态")
    print("-" * 88)
    for it in items:
        if it.expected is None:
            state = "仅报告"
        elif it.ok:
            state = "符合"
        else:
            state = "需调整" if it.fixable else "差异(只读)"
        cur = "(未设)" if it.current is None else it.current
        exp = "(不改)" if it.expected is None else it.expected
        print(pad(it.label, 24) + pad(cur, 26) + pad(exp, 26) + state)
    print()

    for it in items:
        if not it.ok or it.expected is None:
            print(f"  · {it.label}：{it.detail}" + (f"（{it.note}）" if it.note else ""))

    todo = [i for i in bad if i.fixable]
    if do_apply and todo:
        print()
        for it in todo:
            it.apply_fn()
            print(f"  已改：{it.label} → {it.expected}")
        print()
        print("备份目录：" + str(BACKUP_DIR))
        print("变更日志：" + str(LOG_FILE))
        print("⚠️  " + FIX_HINT)
    elif todo:
        print()
        print("下一步：确认后执行  python self_tune.py apply --yes")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(prog="self_tune.py", description="本机环境体检与自动调参")
    ap.add_argument("mode", nargs="?", default="check", choices=["check", "apply"])
    ap.add_argument("--yes", action="store_true", help="apply 时确认执行")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--only", default="", help="只处理这些键，逗号分隔")
    ap.add_argument("--profile", default=str(EXPECTED_FILE), help="预期值清单路径")
    args = ap.parse_args()

    try:
        expected = read_json(Path(args.profile))
    except Exception as exc:  # noqa: BLE001
        print(f"读取预期清单失败：{exc}", file=sys.stderr)
        return 2

    try:
        items = build_items(expected)
    except Exception as exc:  # noqa: BLE001
        print(f"体检过程出错（配置文件可能损坏，已停止）：{exc}", file=sys.stderr)
        return 2

    if args.only:
        want = {k.strip() for k in args.only.split(",") if k.strip()}
        items = [i for i in items if i.key in want]

    do_apply = args.mode == "apply" and args.yes

    if args.json:
        print(json.dumps(
            {"items": [i.as_dict() for i in items],
             "applied": do_apply and any(not i.ok and i.fixable for i in items)},
            ensure_ascii=False, indent=2))
    else:
        render(items, do_apply)

    if args.mode == "apply" and not args.yes:
        print("（未带 --yes，只打印计划，没有改动任何东西）")

    # apply 完成后重新体检一次，用实际状态决定退出码
    if do_apply:
        items = build_items(expected)
        if args.only:
            want = {k.strip() for k in args.only.split(",") if k.strip()}
            items = [i for i in items if i.key in want]

    return 0 if all(i.ok for i in items) else 1


if __name__ == "__main__":
    sys.exit(main())
