#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""win-tune — Windows 体检 / 电源与合盖 / 启动项治理 / 磁盘清理扫描 / 安全修正。

用法：
    python win_tune.py audit                  # 只读体检（默认）
    python win_tune.py audit --json
    python win_tune.py audit --only pagefile,visualfx,power
    python win_tune.py startup                # 启动项全量审计
    python win_tune.py cleanup                # 磁盘可清理项扫描（只读）
    python win_tune.py apply --visualfx --deliveryopt --yes
    python win_tune.py apply --power-nosleep --yes
    python win_tune.py apply --pagefile 16384 32768 --yes

退出码：0 全符合 / 1 有差异 / 2 出错 / 3 缺管理员权限
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from ctypes import wintypes
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
BASELINE_FILE = SKILL_DIR / "config" / "baseline.json"

IS_WIN = sys.platform == "win32"

# ---------------------------------------------------------------- 常量

MM_KEY = r"SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management"
VISUALFX_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects"
DESKTOP_KEY = r"Control Panel\Desktop"
EXPLORER_ADV = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced"
DO_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\DeliveryOptimization\Config"
GPU_CLASS = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"

# ---- 电源 / 合盖 / 锁屏 ----
POWER_SCHEMES = r"SYSTEM\CurrentControlSet\Control\Power\User\PowerSchemes"
SUB_BUTTONS = "4f971e89-eebd-4455-a8de-9e59040e7347"     # 电源按钮和盖子
LIDACTION = "5ca83367-6e45-459f-a27b-476b1d01c936"       # 合上盖子时
SUB_SLEEP = "238c9fa8-0aad-41ed-83f4-97be242c8f20"       # 睡眠
STANDBYIDLE = "29f6c1db-86da-48c5-9fdb-f2b67b1f44da"     # 睡眠之后（闲置多久睡）
HIBERNATEIDLE = "9d7815a6-7ee4-497e-8888-515a05f02364"   # 休眠之后（闲置多久休眠）
SUB_VIDEO = "7516b95f-f776-4464-8c99-403798f61111"       # 显示（GUID，读注册表用）
SUB_VIDEO_ALIAS = "SUB_VIDEO"                            # powercfg 只认别名，不认组 GUID
VIDEOIDLE = "3c0bc021-c8a8-4e07-a973-6b14cbcb2b7e"       # 在此时间后关闭显示
SUB_NONE = "SUB_NONE"                                    # 无子组（含隐藏设置）
CONSOLELOCK = "0e796bdb-100d-47d6-a2d5-f7d2daa51f51"     # 唤醒时需要密码
WINLOGON_KEY = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"
POWER_KEY = r"SYSTEM\CurrentControlSet\Control\Power"
# 0=不操作 1=睡眠 2=休眠 3=关机（部分机型另有 4=关闭显示器）
LID_NAME = {0: "不操作", 1: "睡眠", 2: "休眠", 3: "关机", 4: "关闭显示器"}

RUN_LOCATIONS = [
    ("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run", "HKLM"),
    ("HKLM-WOW64", r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run", "HKLM"),
    ("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run", "HKCU"),
    ("HKCU-WOW64", r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run", "HKCU"),
]

# Start 值：0=Boot 1=System 2=Auto 3=Manual 4=Disabled
SERVICE_START_NAME = {0: "Boot", 1: "System", 2: "Auto", 3: "Manual", 4: "Disabled"}

MEDIA_EXT = {
    ".mp4", ".mov", ".mkv", ".avi", ".png", ".jpg", ".jpeg", ".webp",
    ".wav", ".m4a", ".aac", ".flac", ".bmp", ".gif",
}


# ---------------------------------------------------------------- 基础工具


def dwidth(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in str(s))


def pad(s, width: int) -> str:
    s = str(s)
    return s + " " * max(0, width - dwidth(s))


def human(n: float) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def load_baseline(path: Path = BASELINE_FILE) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def is_admin() -> bool:
    if not IS_WIN:
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


# ---------------------------------------------------------------- 注册表读取


def reg_read(hive: str, key: str, name: str = ""):
    """读注册表值；不存在返回 None。name 为空时读默认值。"""
    if not IS_WIN:
        return None
    import winreg

    h = winreg.HKEY_LOCAL_MACHINE if hive.upper() == "HKLM" else winreg.HKEY_CURRENT_USER
    access = winreg.KEY_READ | winreg.KEY_WOW64_64KEY
    try:
        with winreg.OpenKey(h, key, 0, access) as k:
            val, _ = winreg.QueryValueEx(k, name)
            return val
    except OSError:
        return None


def reg_list_values(hive: str, key: str) -> list[tuple[str, object]]:
    """列出某键下全部值对，保持原始名称（含前导空格）。"""
    if not IS_WIN:
        return []
    import winreg

    h = winreg.HKEY_LOCAL_MACHINE if hive.upper() == "HKLM" else winreg.HKEY_CURRENT_USER
    out: list[tuple[str, object]] = []
    try:
        with winreg.OpenKey(h, key, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            i = 0
            while True:
                try:
                    n, v, _ = winreg.EnumValue(k, i)
                except OSError:
                    break
                out.append((n, v))
                i += 1
    except OSError:
        pass
    return out


def reg_write_dword(hive: str, key: str, name: str, value: int) -> None:
    import winreg

    h = winreg.HKEY_LOCAL_MACHINE if hive.upper() == "HKLM" else winreg.HKEY_CURRENT_USER
    with winreg.CreateKeyEx(h, key, 0, winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as k:
        winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, value)


def reg_write_str(hive: str, key: str, name: str, value: str) -> None:
    import winreg

    h = winreg.HKEY_LOCAL_MACHINE if hive.upper() == "HKLM" else winreg.HKEY_CURRENT_USER
    with winreg.CreateKeyEx(h, key, 0, winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as k:
        winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)


def reg_write_binary(hive: str, key: str, name: str, data: bytes) -> None:
    import winreg

    h = winreg.HKEY_LOCAL_MACHINE if hive.upper() == "HKLM" else winreg.HKEY_CURRENT_USER
    with winreg.CreateKeyEx(h, key, 0, winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as k:
        winreg.SetValueEx(k, name, 0, winreg.REG_BINARY, data)


def reg_write_multisz(hive: str, key: str, name: str, items: list[str]) -> None:
    import winreg

    h = winreg.HKEY_LOCAL_MACHINE if hive.upper() == "HKLM" else winreg.HKEY_CURRENT_USER
    with winreg.CreateKeyEx(h, key, 0, winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as k:
        winreg.SetValueEx(k, name, 0, winreg.REG_MULTI_SZ, items)


# ---------------------------------------------------------------- 系统信息


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def mem_info() -> dict:
    """返回物理内存、提交上限、已提交、可用（字节）。"""
    if not IS_WIN:
        return {}
    st = MEMORYSTATUSEX()
    st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    try:
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
    except Exception:
        return {}
    total_pf = st.ullTotalPageFile           # 物理 + 页面文件 = 当前提交上限
    avail_pf = st.ullAvailPageFile
    return {
        "phys_total": st.ullTotalPhys,
        "phys_avail": st.ullAvailPhys,
        "commit_limit": total_pf,
        "commit_avail": avail_pf,
        "commit_used": max(0, total_pf - avail_pf),
        "mem_load": st.dwMemoryLoad,
    }


def disk_info(drive: str) -> dict:
    if not IS_WIN:
        return {}
    free = ctypes.c_ulonglong(0)
    total = ctypes.c_ulonglong(0)
    ok = ctypes.windll.kernel32.GetDiskFreeSpaceExW(
        ctypes.c_wchar_p(drive + "\\"), None, ctypes.byref(total), ctypes.byref(free)
    )
    if not ok:
        return {}
    return {"total": total.value, "free": free.value, "used": total.value - free.value}


def all_drives() -> list[str]:
    if not IS_WIN:
        return []
    buf = ctypes.create_unicode_buffer(512)
    n = ctypes.windll.kernel32.GetLogicalDriveStringsW(256, buf)
    return [d for d in "".join(buf[:n]).split("\x00") if d.strip()]


def dir_size(path: str, limit_files: int = 400000) -> tuple[int, int]:
    """递归统计目录字节数；不跟随符号链接，防死循环。"""
    total = 0
    count = 0
    stack = [path]
    seen = set()
    while stack:
        cur = stack.pop()
        if cur in seen or count > limit_files:
            continue
        seen.add(cur)
        try:
            with os.scandir(cur) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        else:
                            total += e.stat(follow_symlinks=False).st_size
                            count += 1
                    except OSError:
                        continue
        except OSError:
            continue
    return total, count


def file_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def expand(p: str) -> str:
    return os.path.expandvars(p)


def pending_reboot() -> list[str]:
    if not IS_WIN:
        return []
    out = []
    checks = [
        (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending", None, "CBS"),
        (r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired", None, "WU"),
        (r"SYSTEM\CurrentControlSet\Control\Session Manager", "PendingFileRenameOperations", "FileRename"),
    ]
    for key, name, tag in checks:
        if name is None:
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key):
                    out.append(tag)
            except OSError:
                pass
        elif reg_read("HKLM", key, name):
            out.append(tag)
    return out


# ---------------------------------------------------------------- 采集器


def probe_pagefile() -> dict:
    raw = reg_read("HKLM", MM_KEY, "PagingFiles")
    entries = list(raw) if isinstance(raw, (list, tuple)) else ([raw] if raw else [])
    files = {}
    for e in entries:
        s = str(e).strip()
        if not s:
            continue
        toks = s.split()
        drive = toks[0]
        init = int(toks[1]) if len(toks) > 1 and toks[1].isdigit() else 0
        mx = int(toks[2]) if len(toks) > 2 and toks[2].isdigit() else 0
        files[drive] = {"initial_mb": init, "max_mb": mx, "raw": s}
        files[drive]["allocated_mb"] = round(file_size(drive) / 1048576)
    return {"entries": entries, "files": files}


def probe_visualfx() -> dict:
    vfx = reg_read("HKCU", VISUALFX_KEY, "VisualFXSetting")
    mask = reg_read("HKCU", DESKTOP_KEY, "UserPreferencesMask")
    fs = reg_read("HKCU", DESKTOP_KEY, "FontSmoothing")
    mask_hex = " ".join(f"{b:02X}" for b in mask) if isinstance(mask, (bytes, bytearray)) else None
    return {"VisualFXSetting": vfx, "UserPreferencesMask": mask_hex, "FontSmoothing": fs}


def probe_deliveryopt() -> dict:
    return {"DODownloadMode": reg_read("HKLM", DO_KEY, "DODownloadMode")}


# ---------------------------------------------------------------- 电源采集


def powercfg(args: list[str]) -> int:
    """调 powercfg，吞掉输出只回退出码。-1 表示调用失败。"""
    try:
        r = subprocess.run(["powercfg"] + args, capture_output=True, timeout=25)
        return r.returncode
    except Exception:
        return -1


def _run_text(cmd: list[str], timeout: int = 20) -> str:
    """跑命令并稳妥解码。powercfg 输出是 OEM 代码页(中文=cp936)，
    直接 text=True 会按 UTF-8 解，中文全被 errors=ignore 吃掉。"""
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except Exception:
        return ""
    raw = r.stdout or b""
    for enc in ("utf-8", "cp936", "mbcs"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("latin-1", "ignore")


def _find_guids(text: str) -> list[str]:
    pat = (r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
           r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
    out = []
    for g in re.findall(pat, text or ""):
        g = g.lower()
        if g not in out:
            out.append(g)
    return out


def active_scheme() -> str:
    """当前电源方案 GUID。powercfg 输出随语言变，只认 GUID。"""
    g = _find_guids(_run_text(["powercfg", "/getactivescheme"], 15))
    return g[0] if g else ""


def all_schemes() -> list[str]:
    return _find_guids(_run_text(["powercfg", "/list"], 15))


def _scheme_vals(scheme: str, sub: str, setting: str) -> tuple[int | None, int | None]:
    key = f"{POWER_SCHEMES}\\{scheme}\\{sub}\\{setting}"
    ac = reg_read("HKLM", key, "ACSettingIndex")
    dc = reg_read("HKLM", key, "DCSettingIndex")
    return ac, dc


def _hex_after(text: str, guid: str) -> list[int]:
    """在 /qh 输出里定位 guid 那一块，按出现顺序取出所有 0x 十六进制值。
    每块的结构固定是「可能的设置索引 / 可能的设置友好名称」若干对，
    最后两行是「当前交流电源设置索引」「当前直流电源设置索引」，
    所以取末尾两个即为 AC、DC —— 这样不用认中文标签，也不怕换语言。"""
    lines = (text or "").splitlines()
    start = -1
    for i, l in enumerate(lines):
        if guid in l.lower():
            start = i
            break
    if start < 0:
        return []
    vals = []
    for l in lines[start + 1:]:
        ls = l.strip()
        # 下一块开始就收手
        if ls.lower().startswith("电源设置 guid") or ls.lower().startswith("power setting guid"):
            break
        if guid in ls.lower():
            continue
        for m in re.findall(r"0x([0-9a-fA-F]{1,8})", ls):
            vals.append(int(m, 16))
    return vals


def powercfg_setting(scheme: str, sub_alias: str, setting: str,
                     sub_guid: str = "") -> tuple[int | None, int | None]:
    """读某个电源设置的 AC/DC 索引，返回 (ac, dc)。

    为什么直连 powercfg 而不是像 _scheme_vals 那样读注册表：
    CONSOLELOCK 带 SECURITYDESCRIPTOR 属性，值存在 SECURITY 库而非
    `PowerSchemes\\<方案>\\<组>\\<设置>` 下（实测两个方案都搜不到这个子键），
    普通管理员用 winreg 读只会得到「未设置」。必须解析 `powercfg /qh`。
    另外该设置是**隐藏**的，`/q` 看不到，必须带 h。

    sub_alias 传 `SUB_VIDEO` / `SUB_NONE` 这类**别名**；powercfg 不认
    `7516b95f-...` 这种组 GUID（实测返回 rc=1、输出 19 字节的用法提示）。
    """
    vals = _hex_after(_run_text(["powercfg", "/qh", scheme, sub_alias], 25), setting)
    if len(vals) >= 2:
        return vals[-2], vals[-1]
    if len(vals) == 1:
        return vals[0], vals[0]
    # 兜底：注册表（VIDEOIDLE 这类普通设置确实存在注册表里）
    if sub_guid:
        return _scheme_vals(scheme, sub_guid, setting)
    return None, None


class _POWER_STATUS(ctypes.Structure):
    _fields_ = [("ACLineStatus", wintypes.BYTE),
                ("BatteryFlag", wintypes.BYTE),
                ("BatteryLifePercent", wintypes.BYTE),
                ("Reserved1", wintypes.BYTE),
                ("BatteryLifeTime", wintypes.DWORD),
                ("BatteryFullLifeTime", wintypes.DWORD)]


def has_battery() -> bool:
    """BatteryFlag == 128 表示 No system battery。用它判笔记本，比 CIM 快。"""
    try:
        st = _POWER_STATUS()
        if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(st)):
            return False
        return st.BatteryFlag != 128
    except Exception:
        return False


def modern_standby_only() -> bool:
    """只支持 S0 低电量待机、没有 S3 时为真——这类机器合盖必进 Modern Standby。
    先用语言无关的注册表 CsEnabled，读不到再退回解析 powercfg /a。"""
    cs = reg_read("HKLM", POWER_KEY, "CsEnabled")
    if cs == 1:
        return True
    out = _run_text(["powercfg", "/a"])
    if not out:
        return False
    head = out
    for m in ("此系统上没有", "The following sleep states are not available"):
        if m in out:
            head = out.split(m)[0]
            break
    return "S0" in head and "S3" not in head


def probe_power() -> dict:
    sg = active_scheme()
    schemes = {}
    for g in all_schemes():
        lid_ac, lid_dc = _scheme_vals(g, SUB_BUTTONS, LIDACTION)
        slp_ac, slp_dc = _scheme_vals(g, SUB_SLEEP, STANDBYIDLE)
        cl_ac, cl_dc = powercfg_setting(g, SUB_NONE, CONSOLELOCK)
        vi_ac, vi_dc = powercfg_setting(g, SUB_VIDEO_ALIAS, VIDEOIDLE, SUB_VIDEO)
        schemes[g] = {"lid_ac": lid_ac, "lid_dc": lid_dc,
                      "sleep_ac": slp_ac, "sleep_dc": slp_dc,
                      "consolelock_ac": cl_ac, "consolelock_dc": cl_dc,
                      "videoidle_ac": vi_ac, "videoidle_dc": vi_dc}
    cur = schemes.get(sg, {})
    return {
        "active_scheme": sg,
        "schemes": schemes,
        "lid_ac": cur.get("lid_ac"),
        "lid_dc": cur.get("lid_dc"),
        "sleep_ac": cur.get("sleep_ac"),
        "sleep_dc": cur.get("sleep_dc"),
        "consolelock_ac": cur.get("consolelock_ac"),
        "consolelock_dc": cur.get("consolelock_dc"),
        "videoidle_ac": cur.get("videoidle_ac"),
        "videoidle_dc": cur.get("videoidle_dc"),
        "screensave_active": reg_read("HKCU", DESKTOP_KEY, "ScreenSaveActive"),
        "screensave_secure": reg_read("HKCU", DESKTOP_KEY, "ScreenSaverIsSecure"),
        "screensave_timeout": reg_read("HKCU", DESKTOP_KEY, "ScreenSaveTimeOut"),
        "enable_goodbye": reg_read("HKLM", WINLOGON_KEY, "EnableGoodbye"),
        "hibernate_enabled": reg_read("HKLM", POWER_KEY, "HibernateEnabled"),
        "has_battery": has_battery(),
        "modern_standby_only": modern_standby_only(),
    }


def normalize_date(raw: str) -> str:
    """注册表里的 DriverDate 常见格式是 9-3-2026（月-日-年），统一成 2026-09-03。"""
    s = str(raw).strip()
    if not s:
        return ""
    for sep in ("-", "/"):
        parts = [p for p in s.split(sep) if p]
        if len(parts) == 3 and all(p.isdigit() for p in parts):
            a, b, c = parts
            if len(c) == 4:            # 月-日-年
                return f"{c}-{int(a):02d}-{int(b):02d}"
            if len(a) == 4:            # 年-月-日
                return f"{a}-{int(b):02d}-{int(c):02d}"
    return s


def probe_gpu() -> dict:
    """从显卡类注册表枚举所有子键，取带 DriverVersion 的那一个。"""
    import winreg

    results = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, GPU_CLASS, 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as root:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(root, i)
                except OSError:
                    break
                i += 1
                if not sub.isdigit():
                    continue
                try:
                    with winreg.OpenKey(root, sub, 0, winreg.KEY_READ) as k:
                        desc, _ = winreg.QueryValueEx(k, "DriverDesc")
                        ver, _ = winreg.QueryValueEx(k, "DriverVersion")
                        try:
                            date, _ = winreg.QueryValueEx(k, "DriverDate")
                        except OSError:
                            date = ""
                        results.append({"desc": desc, "version": ver,
                                        "date": normalize_date(date)})
                except OSError:
                    continue
    except OSError:
        pass
    return results[0] if results else {}


def probe_startup_run() -> list[dict]:
    out = []
    for label, key, hive in RUN_LOCATIONS:
        for name, value in reg_list_values(hive, key):
            out.append({
                "location": label,
                "name": name,
                "value": str(value),
                "leading_space": name.startswith(" ") or name != name.strip(),
                "non_ascii": any(ord(c) > 127 for c in name),
            })
    return out


def probe_auto_services() -> list[dict]:
    """列出 Start=2 且二进制不在 C:\\Windows 下的服务。"""
    import winreg

    out = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Services",
                            0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as root:
            i = 0
            while True:
                try:
                    name = winreg.EnumKey(root, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(root, name, 0, winreg.KEY_READ) as k:
                        start, _ = winreg.QueryValueEx(k, "Start")
                        if start != 2:
                            continue
                        try:
                            img, _ = winreg.QueryValueEx(k, "ImagePath")
                        except OSError:
                            img = ""
                        img = str(img).strip('"')
                        low = img.lower()
                        # 只保留「绝对盘符路径、且不在 Windows 目录下」的第三方服务。
                        # svchost 系（%SystemRoot%）、驱动（\SystemRoot\）、
                        # DriverStore 里的组件都不算第三方自启。
                        if not (len(low) > 2 and low[1] == ":" and low[2] in "\\/"):
                            continue
                        if low.startswith("c:\\windows") or "\\windows\\" in low:
                            continue
                        if "svchost" in low or "driverstore" in low:
                            continue
                        try:
                            disp, _ = winreg.QueryValueEx(k, "DisplayName")
                        except OSError:
                            disp = name
                        out.append({"name": name, "display": str(disp), "image": img})
                except OSError:
                    continue
    except OSError:
        pass
    return out


# ---------------------------------------------------------------- 输出


def section(title: str) -> None:
    print()
    print("=" * 4 + " " + title + " " + "=" * max(0, 66 - dwidth(title)))


def table(rows: list[tuple], headers: list[str], widths: list[int]) -> None:
    print("  " + "  ".join(pad(h, w) for h, w in zip(headers, widths)))
    for r in rows:
        print("  " + "  ".join(pad(c, w) for c, w in zip(r, widths)))


# ---------------------------------------------------------------- audit


def cmd_audit(args) -> int:
    base = load_baseline()
    only = {s.strip() for s in args.only.split(",")} if args.only else None

    def want(k: str) -> bool:
        return only is None or k in only

    diffs: list[dict] = []
    report: dict = {"generated": time.strftime("%Y-%m-%d %H:%M:%S")}

    mem = mem_info()
    pf = probe_pagefile()
    vfx = probe_visualfx()
    do = probe_deliveryopt()
    gpu = probe_gpu()
    pw = probe_power()
    report.update({"memory": mem, "pagefile": pf, "visualfx": vfx,
                   "deliveryopt": do, "gpu": gpu, "power": pw,
                   "pending_reboot": pending_reboot()})

    if args.json:
        json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
        print()
        return _exit_code(diffs)

    print(f"win-tune 体检  {report['generated']}   管理员={'是' if is_admin() else '否'}")

    # ---- 页面文件 ----
    if want("pagefile") or want("commit"):
        section("页面文件与提交上限")
        expected = base["pagefile"]["expected_entries"]
        for drive, info in pf["files"].items():
            ok = any(e.startswith(drive + " ") and
                     str(info["initial_mb"]) in e and str(info["max_mb"]) in e
                     for e in expected)
            mark = "OK" if ok else "差异"
            print(f"  {pad(drive, 20)} 设置 {info['initial_mb']}-{info['max_mb']} MB"
                  f"   已分配 {info['allocated_mb']} MB   [{mark}]")
            if not ok:
                diffs.append({"item": f"pagefile:{drive}", "current": info["raw"],
                              "expected": " | ".join(expected)})
        if not pf["files"]:
            print("  （注册表未设置页面文件，说明由系统托管）")
        pf_configured_ok = all(
            any(e.startswith(d + " ") and str(pf["files"][d]["initial_mb"]) in e
                and str(pf["files"][d]["max_mb"]) in e for e in expected)
            for d in pf["files"]
        ) if pf["files"] else False

        if mem:
            limit_gb = mem["commit_limit"] / 2**30
            used_gb = mem["commit_used"] / 2**30
            min_gb = base.get("commit_limit_min_gb", 0)
            if limit_gb >= min_gb:
                mark, note = "OK", ""
            elif pf_configured_ok:
                mark, note = "待重启", "  注册表已达标，重启后才会扩容"
            else:
                mark, note = "偏低", ""
            print(f"  提交上限 {limit_gb:.2f} GB / 已提交 {used_gb:.2f} GB / "
                  f"余量 {limit_gb - used_gb:.2f} GB   [{mark}]{note}")
            if limit_gb < min_gb and not pf_configured_ok:
                diffs.append({"item": "commit_limit", "current": f"{limit_gb:.2f} GB",
                              "expected": f">= {min_gb} GB"})
            print(f"  物理内存 {mem['phys_total']/2**30:.1f} GB / "
                  f"可用 {mem['phys_avail']/2**30:.1f} GB / 负载 {mem['mem_load']}%")

    # ---- 视觉特效 ----
    if want("visualfx"):
        section("视觉特效")
        exp = base["visualfx"]
        rows = []
        for k in ("VisualFXSetting", "UserPreferencesMask", "FontSmoothing"):
            cur = vfx.get(k)
            cur_s = str(cur) if cur is not None else "(未设)"
            good = cur_s.upper() == str(exp[k]).upper()
            rows.append((k, cur_s, str(exp[k]), "OK" if good else "差异"))
            if not good:
                diffs.append({"item": f"visualfx:{k}", "current": cur_s, "expected": str(exp[k])})
        table(rows, ["键", "现值", "期望", "判定"], [24, 30, 26, 6])

    # ---- 传递优化 ----
    if want("deliveryopt"):
        section("传递优化（P2P 上传）")
        cur = do["DODownloadMode"]
        exp = base["deliveryopt"]["DODownloadMode"]
        good = cur == exp
        print(f"  DODownloadMode = {cur if cur is not None else '(未设=默认P2P)'}"
              f"   期望 {exp} (仅HTTP)   [{'OK' if good else '差异'}]")
        if not good:
            diffs.append({"item": "deliveryopt", "current": cur, "expected": exp})

    # ---- 电源 · 合盖 · 锁屏 ----
    if want("power"):
        section("电源 · 合盖 · 锁屏")
        exp = base.get("power", {})
        print(f"  平台：{'笔记本（有电池）' if pw['has_battery'] else '台式机（无电池）'}"
              f"   现代待机 S0：{'仅支持S0，无S3' if pw['modern_standby_only'] else '否'}"
              f"   休眠：{'启用' if pw['hibernate_enabled'] else '关闭'}")
        if pw["modern_standby_only"]:
            print("  提示：这类机器合盖/闲置默认进 Modern Standby，后台任务会断。")

        rows = []
        for key, label, cur_ac, cur_dc, exp_v in (
            ("lid", "合盖动作", pw["lid_ac"], pw["lid_dc"], exp.get("lid_action")),
            ("sleep", "闲置睡眠", pw["sleep_ac"], pw["sleep_dc"], exp.get("sleep_idle_dc")),
        ):
            if exp_v is None:
                continue
            if key == "lid":
                ac_s = LID_NAME.get(cur_ac, str(cur_ac))
                dc_s = LID_NAME.get(cur_dc, str(cur_dc))
                good = (cur_ac == exp_v and cur_dc == exp_v)
            else:
                ac_s = "从不" if cur_ac in (0, None) else f"{cur_ac}s"
                dc_s = "从不" if cur_dc in (0, None) else f"{cur_dc}s"
                good = (cur_dc == exp_v)
            rows.append((label, f"AC={ac_s}", f"DC={dc_s}", "OK" if good else "差异"))
            if not good:
                diffs.append({"item": f"power:{label}",
                              "current": f"AC={ac_s} DC={dc_s}",
                              "expected": LID_NAME.get(exp_v, str(exp_v)) if key == "lid"
                              else "DC=从不"})

        ss_v = pw["screensave_active"]
        ss_ok = str(ss_v) == str(exp.get("screensave_active", "0"))
        rows.append(("屏幕保护", f"Active={ss_v}", f"Secure={pw['screensave_secure']}",
                     "OK" if ss_ok else "差异"))
        if not ss_ok:
            diffs.append({"item": "power:屏幕保护", "current": f"Active={ss_v}",
                          "expected": "Active=0"})

        # 唤醒时需要密码 —— 自动锁屏的真正开关，隐藏设置，只能从 powercfg /qh 读
        cl_exp = exp.get("consolelock")
        cl_ac, cl_dc = pw.get("consolelock_ac"), pw.get("consolelock_dc")
        if cl_ac is None and cl_dc is None:
            rows.append(("唤醒时需密码", "读取失败", "（用 powercfg /qh 复查）", "未知"))
        else:
            cl_ok = True if cl_exp is None else (
                cl_ac == cl_exp and cl_dc == cl_exp)
            yn = {0: "否", 1: "是"}
            rows.append(("唤醒时需密码", f"AC={yn.get(cl_ac, cl_ac)}",
                         f"DC={yn.get(cl_dc, cl_dc)}",
                         "OK" if cl_ok else "差异"))
            if not cl_ok:
                diffs.append({"item": "power:唤醒时需密码",
                              "current": f"AC={cl_ac} DC={cl_dc}",
                              "expected": f"AC=DC={cl_exp}"})

        # 关闭显示器超时（黑屏时间）
        def _secs(v):
            if v is None:
                return "?"
            if v == 0:
                return "从不"
            return f"{v // 60}分" if v % 60 == 0 else f"{v}秒"

        vi_ac, vi_dc = pw.get("videoidle_ac"), pw.get("videoidle_dc")
        vi_ea, vi_ed = exp.get("display_off_idle_ac"), exp.get("display_off_idle_dc")
        if vi_ac is not None or vi_dc is not None:
            vi_ok = True
            if vi_ea is not None:
                vi_ok = vi_ok and vi_ac == vi_ea
            if vi_ed is not None:
                vi_ok = vi_ok and vi_dc == vi_ed
            rows.append(("关闭显示器", f"AC={_secs(vi_ac)}", f"DC={_secs(vi_dc)}",
                         "OK" if vi_ok else "差异"))
            if not vi_ok:
                diffs.append({"item": "power:关闭显示器",
                              "current": f"AC={vi_ac} DC={vi_dc}",
                              "expected": f"AC={vi_ea} DC={vi_ed}"})

        gb_v = pw["enable_goodbye"]
        gb_ok = (gb_v in (0, None))
        rows.append(("动态锁", f"EnableGoodbye={gb_v}", "（0=关）", "OK" if gb_ok else "差异"))
        if not gb_ok:
            diffs.append({"item": "power:动态锁", "current": f"EnableGoodbye={gb_v}",
                          "expected": "0"})

        table(rows, ["项", "接电源(AC)", "电池(DC)", "判定"], [12, 18, 20, 6])
        if any(r[3] == "差异" for r in rows) and exp:
            print("  修正：apply --power-nosleep --yes")

    # ---- 显卡驱动 ----
    if want("gpu"):
        section("显卡驱动（仅报告）")
        if gpu:
            print(f"  {gpu['desc']}")
            print(f"  版本 {gpu['version']}   日期 {gpu.get('date', '?')}"
                  f"   基线 {base['gpu']['expected_version']}")
            if gpu["version"] != base["gpu"]["expected_version"]:
                print(f"  提示：与基线不同。11–14 代核显已进 legacy 分支，"
                      f"升级不再带来性能红利，别为提速而升。")
        else:
            print("  （未能从注册表读到显卡驱动信息）")

    # ---- 磁盘 ----
    if want("disk"):
        section("磁盘")
        for d in all_drives():
            info = disk_info(d.rstrip("\\"))
            if not info:
                continue
            pct = info["used"] / info["total"] * 100 if info["total"] else 0
            flag = ""
            if d.startswith("C") and info["free"] < 20 * 2**30:
                flag = "  <- C 盘偏紧，可跑 cleanup"
            print(f"  {pad(d, 6)} 总 {human(info['total']):>9}  可用 {human(info['free']):>9}"
                  f"  已用 {pct:5.1f}%{flag}")

    # ---- 待重启 ----
    if want("reboot") or only is None:
        section("待重启标志")
        pend = report["pending_reboot"]
        print("  " + ("、".join(pend) if pend else "无"))
        if pend:
            print("  提示：页面文件 / 驱动的改动要重启后才落地。")

    print()
    if diffs:
        print(f"结论：{len(diffs)} 项与基线不符。")
        for d in diffs:
            print(f"  - {d['item']}: 现 {d['current']}  →  期望 {d['expected']}")
    else:
        print("结论：全部符合基线。")
    return _exit_code(diffs)


def _exit_code(diffs) -> int:
    return 0 if not diffs else 1


# ---------------------------------------------------------------- startup


def cmd_startup(args) -> int:
    base = load_baseline()
    protected = {s.lower() for s in base.get("protected_services", [])}
    removable_run = {s.lower() for s in base.get("removable_startup_run", [])}
    removable_svc = {s.lower() for s in base.get("removable_services_manual", [])}
    optional_svc = {s.lower() for s in base.get("optional_services", [])}

    print("启动项全量审计")
    section("A. 注册表 Run（四个位置都必须查）")
    runs = probe_startup_run()
    if not runs:
        print("  （无）")
    for r in runs:
        flags = []
        if r["leading_space"]:
            flags.append("键名有前导空格!")
        if r["non_ascii"]:
            flags.append("含非 ASCII 字符!")
        low = r["name"].strip().lower()
        if low in removable_run:
            flags.append("已标记可删")
        print(f"  [{pad(r['location'], 11)}] {r['name']}")
        print(f"       {r['value'][:110]}")
        if flags:
            print(f"       >>> {' / '.join(flags)}")
    print(f"  合计 {len(runs)} 项")

    section("B. 第三方自动启动服务（Start=Auto）")
    svcs = probe_auto_services()
    rows = []
    for s in svcs:
        low = s["name"].lower()
        if low in protected or any(p in low for p in protected):
            tag = "保护:勿动"
        elif low in removable_svc:
            tag = "可改手动"
        elif low in optional_svc:
            tag = "视需要"
        else:
            tag = ""
        rows.append((s["name"][:30], s["image"][:48], tag))
    table(rows, ["服务名", "可执行文件", "建议"], [30, 48, 10])
    print(f"  合计 {len(svcs)} 项")

    section("C. 绝对不要动的（附理由）")
    reasons = base.get("protected_reason", {})
    for k, v in reasons.items():
        print(f"  {pad(k, 34)} {v}")
    print()
    print("提示：Run 键名可能带前导空格或 ® 等字符，按名字精确匹配会漏。")
    print("参考 references/changes-2026-10-20.md 的实测记录。")
    return 0


# ---------------------------------------------------------------- cleanup


def cmd_cleanup(args) -> int:
    base = load_baseline()
    targets = base["cleanup_targets"]
    print("磁盘可清理项扫描（只读，不删任何文件）")
    section("可清理项")
    rows = []
    total_safe = 0
    total_confirm = 0
    for t in targets:
        path = expand(t["path"])
        if not os.path.exists(path):
            rows.append((t["id"], t["name"], "-", "不存在", t["risk"]))
            continue
        size, cnt = dir_size(path)
        if t["path"].endswith("$Recycle.Bin") or path.endswith("$Recycle.Bin"):
            size, cnt = dir_size(path)
        rows.append((t["id"], t["name"], human(size), f"{cnt} 个", t["risk"]))
        if t["risk"] == "safe":
            total_safe += size
        else:
            total_confirm += size
    table(rows, ["#", "项目", "体积", "文件数", "风险"], [4, 26, 12, 12, 8])
    print()
    print(f"  safe 合计 {human(total_safe)}   需确认合计 {human(total_confirm)}")

    section("绝对不要手删")
    for n in base["never_touch"]:
        p = n["path"]
        size = dir_size(p)[0] if os.path.exists(p) else 0
        print(f"  {pad(p, 34)} {human(size):>10}   {n['reason']}")

    section("清理执行约束（本机实测）")
    print("  1. os.remove 实际是「扔回收站」，不调 SHEmptyRecycleBinW 不释放空间")
    print("  2. 单轮删除 > 50 个文件会被安全策略整体中止")
    print("  3. rd /s /q 在用户目录直接拒（rc=5），>50 个必须写成 .bat 让用户自己跑")
    print("  4. 个人目录一律走回收站，不直接删")
    return 0


# ---------------------------------------------------------------- apply


def backup_dir() -> Path:
    ws = Path.cwd()
    d = ws / f"_wintune_backup-{time.strftime('%Y%m%d-%H%M%S')}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cmd_apply(args) -> int:
    base = load_baseline()
    tasks = []
    if args.visualfx:
        tasks.append("visualfx")
    if args.deliveryopt:
        tasks.append("deliveryopt")
    if args.pagefile:
        tasks.append("pagefile")
    if getattr(args, "power_nosleep", False):
        tasks.append("power")
    if not tasks:
        print("未指定要改什么。可用：--visualfx / --deliveryopt / --power-nosleep / "
              "--pagefile INIT MAX")
        return 2

    need_admin = "deliveryopt" in tasks or "pagefile" in tasks or "power" in tasks
    if need_admin and not is_admin():
        print("需要管理员权限（改 HKLM）。请以管理员身份重跑。")
        return 3

    bk = backup_dir()
    snapshot = {}
    plan = []

    if "visualfx" in tasks:
        snapshot["visualfx"] = probe_visualfx()
        plan.append("视觉特效 → 最佳性能（保留字体平滑）")
    if "deliveryopt" in tasks:
        snapshot["deliveryopt"] = probe_deliveryopt()
        plan.append("传递优化 → DODownloadMode=0（仅 HTTP）")
    if "pagefile" in tasks:
        snapshot["pagefile"] = probe_pagefile()
        plan.append(f"页面文件 → {args.pagefile[0]}–{args.pagefile[1]} MB（重启生效）")
    if "power" in tasks:
        snapshot["power"] = probe_power()
        _pexp = base.get("power", {})
        plan.append("合盖 → 不采取任何操作（AC/DC）")
        plan.append("闲置睡眠 → 从不（电池）；屏保锁屏/动态锁 → 关闭")
        if _pexp.get("consolelock") is not None:
            plan.append(f"唤醒时需密码 → {'是' if int(_pexp['consolelock']) else '否'}"
                        f"（AC/DC，{len(all_schemes())} 个电源方案全覆盖）")
        if _pexp.get("display_off_idle_ac") is not None:
            plan.append(f"关闭显示器 → AC {_pexp['display_off_idle_ac']}s"
                        f" / DC {_pexp.get('display_off_idle_dc') or 0}s")
        plan.append("  写入全部电源方案，并重新激活当前方案")

    (bk / "before.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2),
                                    encoding="utf-8")
    (bk / "rollback.ps1").write_text(_rollback_script(snapshot), encoding="utf-8")

    print(f"备份目录：{bk}")
    print("计划：")
    for p in plan:
        print("  - " + p)
    if not args.yes:
        print("\n未加 --yes，只打印计划，未做任何修改。")
        return 0

    done = []
    if "visualfx" in tasks:
        exp = base["visualfx"]
        reg_write_dword("HKCU", VISUALFX_KEY, "VisualFXSetting", exp["VisualFXSetting"])
        reg_write_binary("HKCU", DESKTOP_KEY, "UserPreferencesMask",
                         bytes(int(x, 16) for x in exp["UserPreferencesMask"].split()))
        reg_write_str("HKCU", DESKTOP_KEY, "FontSmoothing", exp["FontSmoothing"])
        reg_write_str("HKCU", DESKTOP_KEY, "DragFullWindows", "0")
        reg_write_dword("HKCU", EXPLORER_ADV, "ListviewShadow", 0)
        reg_write_dword("HKCU", EXPLORER_ADV, "TaskbarAnimations", 0)
        done.append(("visualfx", probe_visualfx()))

    if "deliveryopt" in tasks:
        reg_write_dword("HKLM", DO_KEY, "DODownloadMode",
                        base["deliveryopt"]["DODownloadMode"])
        done.append(("deliveryopt", probe_deliveryopt()))

    if "pagefile" in tasks:
        init, mx = int(args.pagefile[0]), int(args.pagefile[1])
        drive = base["pagefile"]["drive_for_expansion"]
        cur = probe_pagefile()["entries"]
        new = []
        replaced = False
        for line in cur:
            s = str(line).strip()
            if s.lower().startswith(drive.lower() + "\\pagefile.sys"):
                new.append(f"{drive}\\pagefile.sys {init} {mx}")
                replaced = True
            elif s:
                new.append(s)
        if not replaced:
            new.append(f"{drive}\\pagefile.sys {init} {mx}")
        reg_write_multisz("HKLM", MM_KEY, "PagingFiles", new)
        done.append(("pagefile", probe_pagefile()))

    if "power" in tasks:
        exp = base.get("power", {})
        lid = int(exp.get("lid_action", 0))
        sleep_dc = int(exp.get("sleep_idle_dc", 0))
        cl = exp.get("consolelock")
        vi_ac = exp.get("display_off_idle_ac")
        vi_dc = exp.get("display_off_idle_dc")
        targets = all_schemes() or [active_scheme()]
        rcs = []
        for g in targets:
            if not g:
                continue
            rcs.append(powercfg(["/setacvalueindex", g, SUB_BUTTONS, LIDACTION, str(lid)]))
            rcs.append(powercfg(["/setdcvalueindex", g, SUB_BUTTONS, LIDACTION, str(lid)]))
            rcs.append(powercfg(["/setdcvalueindex", g, SUB_SLEEP, STANDBYIDLE, str(sleep_dc)]))
            if cl is not None:
                rcs.append(powercfg(["/setacvalueindex", g, SUB_NONE, CONSOLELOCK, str(int(cl))]))
                rcs.append(powercfg(["/setdcvalueindex", g, SUB_NONE, CONSOLELOCK, str(int(cl))]))
            if vi_ac is not None:
                rcs.append(powercfg(["/setacvalueindex", g, SUB_VIDEO_ALIAS, VIDEOIDLE,
                                     str(int(vi_ac))]))
            if vi_dc is not None:
                rcs.append(powercfg(["/setdcvalueindex", g, SUB_VIDEO_ALIAS, VIDEOIDLE,
                                     str(int(vi_dc))]))
        # 让人改完立刻生效：重新激活当前方案
        powercfg(["/setactive", "SCHEME_CURRENT"])

        reg_write_str("HKCU", DESKTOP_KEY, "ScreenSaveActive",
                      str(exp.get("screensave_active", "0")))
        reg_write_str("HKCU", DESKTOP_KEY, "ScreenSaverIsSecure",
                      str(exp.get("screensave_secure", "0")))
        reg_write_dword("HKLM", WINLOGON_KEY, "EnableGoodbye",
                        int(exp.get("enable_goodbye", 0)))

        after = probe_power()
        after["_rcs"] = rcs
        after["_schemes_written"] = len([g for g in targets if g])
        done.append(("power", after))

    print("\n已写入：")
    for name, state in done:
        print(f"  {name}: {json.dumps(state, ensure_ascii=False)[:220]}")

    log = Path(os.environ.get("WINTUNE_LOG", bk.parent / "_wintune_log.jsonl"))
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "tasks": tasks,
                            "backup": str(bk)}, ensure_ascii=False) + "\n")

    print("\n生效条件：")
    print("  视觉特效 → 注销或重启后整体生效")
    print("  传递优化 → 立即")
    print("  页面文件 → 必须重启，提交上限才会变")
    print("  合盖/电源 → 立即（已重新激活当前方案）")
    return 0


def _rollback_script(snap: dict) -> str:
    lines = ["# win-tune 回滚脚本（需管理员）", "$ErrorActionPreference = 'Stop'"]
    v = snap.get("visualfx")
    if v:
        ve = r"HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects"
        lines.append(f"Set-ItemProperty '{ve}' -Name VisualFXSetting -Value "
                     f"{v.get('VisualFXSetting') if v.get('VisualFXSetting') is not None else 0} "
                     f"-Type DWord")
        m = v.get("UserPreferencesMask")
        if m:
            b = ",".join("0x" + x for x in m.split())
            lines.append(f"Set-ItemProperty 'HKCU:\\Control Panel\\Desktop' "
                         f"-Name UserPreferencesMask -Value ([byte[]]({b})) -Type Binary")
        if v.get("FontSmoothing") is not None:
            lines.append(f"Set-ItemProperty 'HKCU:\\Control Panel\\Desktop' "
                         f"-Name FontSmoothing -Value '{v['FontSmoothing']}' -Type String")
    d = snap.get("deliveryopt")
    if d and d.get("DODownloadMode") is not None:
        lines.append(f"Set-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion"
                     f"\\DeliveryOptimization\\Config' -Name DODownloadMode -Value "
                     f"{d['DODownloadMode']} -Type DWord")
    p = snap.get("pagefile")
    if p and p.get("entries"):
        arr = ",".join(f"'{e}'" for e in p["entries"])
        lines.append(f"Set-ItemProperty 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Session Manager"
                     f"\\Memory Management' -Name PagingFiles -Value @({arr}) -Type MultiString")
        lines.append("Write-Host '页面文件已还原，需重启生效'")
    pw = snap.get("power")
    if pw:
        for g, v in (pw.get("schemes") or {}).items():
            if v.get("lid_ac") is not None:
                lines.append(f"powercfg /setacvalueindex {g} {SUB_BUTTONS} {LIDACTION} "
                             f"{v['lid_ac']}")
            if v.get("lid_dc") is not None:
                lines.append(f"powercfg /setdcvalueindex {g} {SUB_BUTTONS} {LIDACTION} "
                             f"{v['lid_dc']}")
            if v.get("sleep_dc") is not None:
                lines.append(f"powercfg /setdcvalueindex {g} {SUB_SLEEP} {STANDBYIDLE} "
                             f"{v['sleep_dc']}")
            if v.get("consolelock_ac") is not None:
                lines.append(f"powercfg /setacvalueindex {g} {SUB_NONE} {CONSOLELOCK} "
                             f"{v['consolelock_ac']}")
            if v.get("consolelock_dc") is not None:
                lines.append(f"powercfg /setdcvalueindex {g} {SUB_NONE} {CONSOLELOCK} "
                             f"{v['consolelock_dc']}")
            if v.get("videoidle_ac") is not None:
                lines.append(f"powercfg /setacvalueindex {g} {SUB_VIDEO_ALIAS} {VIDEOIDLE} "
                             f"{v['videoidle_ac']}")
            if v.get("videoidle_dc") is not None:
                lines.append(f"powercfg /setdcvalueindex {g} {SUB_VIDEO_ALIAS} {VIDEOIDLE} "
                             f"{v['videoidle_dc']}")
        lines.append("powercfg /setactive SCHEME_CURRENT")
        for reg, val in (("ScreenSaveActive", pw.get("screensave_active")),
                         ("ScreenSaverIsSecure", pw.get("screensave_secure"))):
            if val is not None:
                lines.append(f"Set-ItemProperty 'HKCU:\\Control Panel\\Desktop' "
                             f"-Name {reg} -Value '{val}' -Type String")
        if pw.get("enable_goodbye") is not None:
            lines.append(f"Set-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\Windows NT"
                         f"\\CurrentVersion\\Winlogon' -Name EnableGoodbye -Value "
                         f"{pw['enable_goodbye']} -Type DWord")
        lines.append("Write-Host '电源/合盖/锁屏已还原，立即生效'")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- main


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(prog="win_tune", description="Windows 体检/启动项/清理/安全修正")
    sub = ap.add_subparsers(dest="cmd")

    a = sub.add_parser("audit", help="只读体检（默认）")
    a.add_argument("--json", action="store_true")
    a.add_argument("--only", default="", help="逗号分隔：pagefile,commit,visualfx,deliveryopt,power,gpu,disk,reboot")

    sub.add_parser("startup", help="启动项全量审计")

    sub.add_parser("cleanup", help="磁盘可清理项扫描（只读）")

    p = sub.add_parser("apply", help="应用安全修正")
    p.add_argument("--visualfx", action="store_true")
    p.add_argument("--deliveryopt", action="store_true")
    p.add_argument("--pagefile", nargs=2, metavar=("INIT_MB", "MAX_MB"))
    p.add_argument("--power-nosleep", action="store_true",
                   help="合盖不操作 + 关闲置睡眠 + 关屏保锁屏 + 关动态锁（写入全部电源方案）")
    p.add_argument("--yes", action="store_true", help="真改；不加只打印计划")

    args = ap.parse_args(argv)
    if not args.cmd:
        args = ap.parse_args(["audit"] + ([] if argv is None else argv))

    if not IS_WIN:
        print("本技能仅适用于 Windows。")
        return 2

    if args.cmd == "audit":
        return cmd_audit(args)
    if args.cmd == "startup":
        return cmd_startup(args)
    if args.cmd == "cleanup":
        return cmd_cleanup(args)
    if args.cmd == "apply":
        return cmd_apply(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
