#!/usr/bin/env python3
"""ps5-dump-forge wrapper: acquire the tool, run it, and verify its output.

Subcommands
-----------
  tool                       Resolve the ps5-dump-forge binary, downloading it if absent.
  inspect <path> [--json]    Describe a game folder / image / .pkg / archive (title, id,
                             version, firmware, image mode, findings).
  convert <source> ...       Pass through to the tool with safe defaults applied
                             (auto output name, name-length guard, geometry check).
  verify <image>             Independent exFAT structural check (does NOT use the tool).
  check-name <name>          Report byte length against the ShadowMountPlus 63/58 limit.

Why this wrapper exists
-----------------------
* The GUI tools on this machine (PS5PKGTool, PS5FpkgBuilderPro, PKGViewer) cannot be
  scripted and PKGViewer/PS5PKGTool stall on "plaintext (PPRPLAIN-NOAUTH)" outer PFS
  images, emitting a metadata-only empty shell. ps5-dump-forge reads them fine.
* Output names must fit ShadowMountPlus's limit, and the exFAT geometry must be
  512-byte sectors / 64 KiB clusters, or the image will not mount. Both are checked
  here so a bad result is caught before it reaches the console.

Only the Python standard library is used.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

REPO = "quer3q/ps5-dump-forge"
TOOL_NAME = "ps5-dump-forge"
DOWNLOAD_DIR = Path.home() / ".workbuddy" / "tools" / TOOL_NAME

# ShadowMountPlus refuses to mount an image whose name (sans extension) exceeds these.
NAME_LIMIT = {".ffpfsc": 58}
NAME_LIMIT_DEFAULT = 63

IS_WINDOWS = os.name == "nt"


def _platform_token() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    arch = {
        "amd64": "x86-64", "x86_64": "x86-64", "x64": "x86-64",
        "arm64": "aarch64", "aarch64": "aarch64",
    }.get(machine, machine)
    if system == "windows":
        return f"windows-{arch}"
    if system == "darwin":
        return f"macos-{arch}"
    return f"linux-{arch}"


def _api(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "ps5-skill/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "ps5-skill/1.0"})
    with urllib.request.urlopen(req, timeout=300) as resp, open(dest, "wb") as fh:
        shutil.copyfileobj(resp, fh)


def _find_local() -> Path | None:
    """Look for an already-extracted binary in the cache or a few obvious places."""
    exe = f"{TOOL_NAME}.exe" if IS_WINDOWS else TOOL_NAME
    candidates = [DOWNLOAD_DIR / exe]
    candidates += sorted(DOWNLOAD_DIR.glob(f"*/{exe}"))
    # A previous session may have left the extracted release next to a workspace.
    for extra in (Path.cwd(), Path.cwd() / "tools", Path.cwd() / "tools" / "forge"):
        candidates += sorted(extra.glob(f"**/{exe}")) if extra.is_dir() else []
    for c in candidates:
        if c.is_file():
            return c
    return None


def ensure_tool(verbose: bool = True) -> Path:
    """Return a usable ps5-dump-forge path, downloading the release if necessary."""
    found = _find_local()
    if found:
        return found

    token = _platform_token()
    if verbose:
        print(f"[forge] no local binary; fetching latest release for {token}", file=sys.stderr)
    try:
        release = _api(f"https://api.github.com/repos/{REPO}/releases/latest")
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"cannot reach GitHub API: {exc}")

    matches = [a for a in release.get("assets", []) if token in a["name"].lower()]
    if not matches:
        names = ", ".join(a["name"] for a in release.get("assets", [])) or "(none)"
        raise SystemExit(f"no asset for {token} in {release.get('tag_name')}. Assets: {names}")
    # Prefer the lightweight CLI build: the "webview2" variants bundle a GUI and are
    # ~40x larger (309 MB vs 8 MB) while doing exactly the same job from the CLI.
    plain = [a for a in matches if "webview" not in a["name"].lower() and "gui" not in a["name"].lower()]
    asset = min(plain or matches, key=lambda a: a["size"])

    if verbose:
        print(f"[forge] downloading {asset['name']} ({asset['size'] / 1e6:.1f} MB)", file=sys.stderr)
    with tempfile.TemporaryDirectory() as tmp:
        zpath = Path(tmp) / asset["name"]
        _download(asset["browser_download_url"], zpath)
        if zpath.suffix.lower() == ".zip":
            with zipfile.ZipFile(zpath) as z:
                z.extractall(DOWNLOAD_DIR)
        else:  # a bare binary
            DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(zpath, DOWNLOAD_DIR / asset["name"])

    exe = f"{TOOL_NAME}.exe" if IS_WINDOWS else TOOL_NAME
    for c in sorted(DOWNLOAD_DIR.rglob(exe)):
        if c.is_file():
            if not IS_WINDOWS:
                c.chmod(c.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
            return c
    raise SystemExit(f"extracted {asset['name']} but found no {exe}' inside")


def run_tool(args: list[str], tool: Path | None = None) -> int:
    tool = tool or ensure_tool()
    cmd = [str(tool), *args]
    return subprocess.call(cmd)


# --------------------------------------------------------------------------- checks

def name_check(name: str) -> tuple[bool, str]:
    """Validate an output file name against the ShadowMountPlus byte limit."""
    p = Path(name)
    ext = p.suffix.lower()
    limit = NAME_LIMIT.get(ext, NAME_LIMIT_DEFAULT)
    stem = p.stem
    nbytes = len(stem.encode("utf-8"))
    ok = nbytes <= limit
    note = "OK" if ok else "TOO LONG — ShadowMountPlus will not mount it"
    return ok, f"{name!r}: stem {nbytes} bytes (limit {limit} for {ext or 'no extension'}) -> {note}"


def image_check(path: Path) -> dict:
    """Parse the exFAT boot sector directly, without trusting the converter."""
    info: dict = {"path": str(path), "problems": []}
    if not path.is_file():
        info["problems"].append("file does not exist")
        return info
    size = path.stat().st_size
    info["size_bytes"] = size
    with open(path, "rb") as fh:
        bs = fh.read(512)
    if bs[3:11] != b"EXFAT   ":
        info["problems"].append(f"not an exFAT volume (FS name = {bs[3:11]!r})")
        return info

    part_off, vol_len = struct.unpack_from("<QQ", bs, 64)
    fat_off, fat_len = struct.unpack_from("<II", bs, 80)
    heap_off, cluster_cnt = struct.unpack_from("<II", bs, 88)
    root_clu, vol_serial = struct.unpack_from("<II", bs, 96)
    fsrev, _flags = struct.unpack_from("<HH", bs, 104)
    bps_shift, spc_shift, nfats = bs[108], bs[109], bs[110]

    sector = 1 << bps_shift
    cluster = sector << spc_shift
    info.update(
        sector_size=sector,
        cluster_size=cluster,
        nfats=nfats,
        volume_bytes=vol_len * sector,
        heap_offset=heap_off,
        cluster_count=cluster_cnt,
        root_cluster=root_clu,
        fs_revision=f"0x{fsrev:04x}",
        volume_serial=f"0x{vol_serial:010x}",
    )
    if sector != 512 or cluster != 65536:
        info["problems"].append(
            f"geometry is {sector} B / {cluster} B; ShadowMountPlus's fast path wants 512 B / 65536 B"
        )

    # Walk the root directory for a quick sanity report.
    volume_label = None
    entries: list[tuple[str, int, int, int]] = []  # kind, name, size, first_cluster
    fh_path = path
    with open(fh_path, "rb") as fh:
        fh.seek(heap_off * sector + (root_clu - 2) * cluster)
        buf = fh.read(cluster)
    i = 0
    while i < len(buf) and buf[i] != 0x00:
        t = buf[i]
        if t == 0x83:  # volume label
            n = buf[i + 1]
            volume_label = buf[i + 2:i + 2 + n * 2].decode("utf-16-le", "replace")
            i += 32
            continue
        if t == 0x85:  # file directory entry
            sec = buf[i + 1]
            attr = struct.unpack_from("<H", buf, i + 4)[0]
            name, size, first = "", 0, 0
            for k in range(1, sec + 1):
                e = buf[i + k * 32:i + (k + 1) * 32]
                if len(e) < 32:
                    break
                if e[0] == 0xC0:
                    first = struct.unpack_from("<I", e, 20)[0]
                    size = struct.unpack_from("<Q", e, 24)[0]
                elif e[0] == 0xC1:
                    for c in range(0, 30, 2):
                        ch = struct.unpack_from("<H", e, 2 + c)[0]
                        if ch:
                            name += chr(ch)
            entries.append(("dir" if attr & 0x10 else "file", name, size, first))
            i += 32 * (sec + 1)
            continue
        i += 32

    info["volume_label"] = volume_label
    info["root_entries"] = sorted(entries, key=lambda x: -x[2])
    if not entries:
        info["problems"].append("root directory is empty")
    else:
        names = " ".join(e[1] for e in entries)
        if "eboot.bin" not in names:
            info["problems"].append("no eboot.bin in the root — not a PS5 app dump?")
    return info


def cmd_tool(args: argparse.Namespace) -> int:
    print(ensure_tool())
    return 0


def cmd_check_name(args: argparse.Namespace) -> int:
    ok, msg = name_check(args.name)
    print(msg)
    return 0 if ok else 1


def cmd_inspect(args: argparse.Namespace) -> int:
    tool = ensure_tool()
    passthrough = ["inspect", args.path]
    if args.json:
        passthrough.append("--json")
    return run_tool(passthrough, tool)


def cmd_convert(args: argparse.Namespace) -> int:
    tool = ensure_tool()
    source = Path(args.source)
    if not source.exists():
        raise SystemExit(f"source not found: {source}")

    ident: dict = {}
    try:
        raw = subprocess.run(
            [str(tool), "inspect", str(source), "--json"],
            capture_output=True, text=True, timeout=600,
        )
        if raw.stdout.strip():
            ident = json.loads(raw.stdout)
    except Exception:  # noqa: BLE001 - a missing inspect is not fatal
        pass

    out = args.output
    if not out:
        title_id = (ident.get("title_id") or ident.get("titleId") or "").strip()
        title = (ident.get("title") or ident.get("title_name") or "").strip()
        version = (ident.get("version") or ident.get("content_version") or "").strip()
        safe = "".join(ch if (ch.isalnum() or ch in "-_.") else "_" for ch in title)
        safe = re.sub(r"_{2,}", "_", safe).strip("_")
        stem = "_".join(p for p in (title_id, safe, version) if p) or "ps5dump"
        out = str(source.with_name(f"{stem}{args.ext}"))

    ok, msg = name_check(out)
    print(f"[forge] {msg}")
    if not ok and not args.force:
        raise SystemExit("pick a shorter -o name, or pass --force to ignore")

    passthrough = ["convert", str(source), "--to", args.to, "-o", out]
    if args.full_verify:
        passthrough.append("--full-verify")
    if args.inner:
        passthrough += ["--inner", args.inner]
    if args.remove_backport:
        passthrough.append("--remove-backport")
    if args.threads:
        passthrough += ["--threads", str(args.threads)]
    if args.kraken:
        passthrough += ["--kraken", args.kraken]

    rc = run_tool(passthrough, tool)
    if rc != 0:
        return rc

    target = Path(out)
    if target.suffix.lower() in (".exfat", ".ffpkg", ".ffpfs", ".ffpfsc"):
        print("\n[forge] independent geometry check:")
        info = image_check(target)
        print(json.dumps({k: v for k, v in info.items() if k != "root_entries"}, indent=2))
        for e in info.get("root_entries", [])[:15]:
            print(f"  [{e[0]}] {e[1]:<20} {e[2]:>12,} bytes")
        if info["problems"]:
            print("\n[forge] PROBLEMS: " + "; ".join(info["problems"]))
            return 2
        print("\n[forge] geometry looks correct.")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    info = image_check(Path(args.image))
    printable = dict(info)
    printable.pop("root_entries", None)
    print(json.dumps(printable, indent=2))
    for e in info.get("root_entries", [])[:25]:
        print(f"  [{e[0]}] {e[1]:<24} {e[2]:>13,} bytes  first_cluster={e[3]}")
    print()
    if info["problems"]:
        print("PROBLEMS:")
        for p in info["problems"]:
            print("  -", p)
        return 2
    print("OK: valid exFAT, correct geometry, PS5 app layout present.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="forge.py", description="ps5-dump-forge wrapper")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("tool", help="resolve/download the tool and print its path")
    p.set_defaults(func=cmd_tool)

    p = sub.add_parser("check-name", help="validate an output name against SMP's byte limit")
    p.add_argument("name")
    p.set_defaults(func=cmd_check_name)

    p = sub.add_parser("inspect", help="describe a source (pkg/folder/image/archive)")
    p.add_argument("path")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("convert", help="convert a source with safe defaults")
    p.add_argument("source")
    p.add_argument("--to", default="exfat",
                   choices=["folder", "exfat", "ffpkg", "ffpfs", "ffpfsc", "pkg", "lz4"])
    p.add_argument("-o", "--output")
    p.add_argument("--ext", default=None,
                   help="extension used when auto-naming (default: derived from --to)")
    p.add_argument("--inner", choices=["exfat", "ffpkg", "ffpfs"])
    p.add_argument("--threads", type=int)
    p.add_argument("--kraken", choices=["fast", "balanced", "smallest", "stored"])
    p.add_argument("--remove-backport", action="store_true")
    p.add_argument("--full-verify", action="store_true")
    p.add_argument("--force", action="store_true", help="ignore the name-length guard")
    p.set_defaults(func=cmd_convert)

    p = sub.add_parser("verify", help="independent exFAT structural check")
    p.add_argument("image")
    p.set_defaults(func=cmd_verify)

    args = ap.parse_args()
    if args.cmd == "convert" and args.ext is None:
        args.ext = "." + args.to if args.to != "folder" else ""
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
