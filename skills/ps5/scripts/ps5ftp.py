#!/usr/bin/env python3
"""PS5 (etaHEN ftpsrv) FTP 助手 —— 只依赖标准库。

用途：直接在电脑上读取/写入主机文件，免去让用户手工操作。
    适合取 SMP 日志、读 config.ini、看沙箱里实际挂了哪些库、传镜像。

用法：
    python ps5ftp.py ls   <远程路径>
    python ps5ftp.py tree <远程路径> [深度]        # 递归列目录（默认深度 2）
    python ps5ftp.py cat  <远程文件>               # 打印文本（自动尝试 utf-8/gbk）
    python ps5ftp.py get  <远程文件> [本地路径]     # 下载
    python ps5ftp.py put  <本地文件> <远程目录>     # 上传（传后自动回传校验）
    python ps5ftp.py find <远程目录> <关键字> [深度] # 按文件名找

连接参数（默认对应用户主机；可用环境变量覆盖）：
    PS5FTP_HOST=<PRIVATE_IP>  PS5FTP_PORT=2121
    PS5FTP_USER=  (空)           PS5FTP_PASS=  (空)

⚠️ 在 Git Bash 里调用时，**必须**先 `export MSYS_NO_PATHCONV=1`。
   否则 shell 会把 `/data/...`、`/mnt/...` 当成本地路径改写掉
   （实测 `/mnt/sandbox/...` 被变成 `D:/Program Files/.../PortableGit/mnt/sandbox/...`），
   服务器 LIST 失败后脚本会退回 MLSD 兜底，而**这台服务器的 MLSD 忽略路径、
   永远返回文件系统根目录** —— 于是你看到的是根目录内容，极易误判成"成功了"。
   用 Python 的 heredoc 内嵌路径（不经 shell 传参）不会触发这个问题。

⚠️ 重要：ftpsrv 对 SELF 有**透明解密**——上传 .sprx/.prx/.self/eboot.bin 后再取回来
   会变成裸 ELF（实测 423350 B 的 FSELF → 466916 B 的 7f454c46 ELF）。
   因此本脚本**默认拒绝**上传这类签名二进制（需 --force 强制，且会警告）。
   要改游戏内容，正确做法是：PC 上改原始目录 → 重打包成镜像 → 传镜像（.exfat 不受影响）。
   另外服务器报的文件大小不可信，put 之后一定会回传比对。
"""
from __future__ import annotations

import hashlib
import io
import os
import ftplib
import sys

HOST = os.environ.get("PS5FTP_HOST", "<PRIVATE_IP>")
PORT = int(os.environ.get("PS5FTP_PORT", "2121"))
USER = os.environ.get("PS5FTP_USER", "anonymous")
PASS = os.environ.get("PS5FTP_PASS", "")
TIMEOUT = 60

# 会被 ftpsrv 透明解密的扩展名 —— 禁止上传
SIGNED_EXT = {".sprx", ".prx", ".self", ".bin", ".elf"}


def connect() -> ftplib.FTP:
    f = ftplib.FTP()
    f.encoding = "utf-8"
    f.connect(HOST, PORT, timeout=TIMEOUT)
    f.login(USER, PASS)
    f.set_pasv(True)
    return f


def listdir(f: ftplib.FTP, path: str):
    """返回 [(名字, 大小str, 是否目录)]。

    ⚠️ 必须优先用 `LIST <path>`：etaHEN 的 ftpsrv 实现了 MLSD，但它
    **忽略路径参数、永远返回文件系统根目录**（实测 2026-10-16）。
    用 MLSD 会导致「列任何目录都得到根目录内容」这一极迷惑人的假象。
    MLSD 只在 LIST 失败时作为兜底。
    """
    rows = []
    try:
        f.retrlines("LIST " + path, rows.append)
    except Exception:
        rows = []
    if rows:
        out = []
        for r in rows:
            parts = r.split(None, 8)
            if len(parts) < 9:
                continue
            name = parts[-1]
            if name in (".", ".."):
                continue
            out.append((name, parts[4], r[:1].lower() == "d"))
        return out
    # 兜底：MLSD（注意它可能不认路径）
    out = []
    try:
        for name, facts in f.mlsd(path):
            if name in (".", ".."):
                continue
            isdir = facts.get("type", "") in ("dir", "cdir", "pdir")
            out.append((name, facts.get("size", "") if not isdir else "", isdir))
    except Exception as e:
        return [("ERR %s" % e, "", False)]
    return out


def human(n) -> str:
    try:
        v = float(n)
    except Exception:
        return str(n)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if v < 1024 or u == "TB":
            return "%.1f %s" % (v, u) if u != "B" else "%d B" % v
        v /= 1024
    return str(n)


def cmd_ls(f, path):
    for name, size, isdir in listdir(f, path):
        if isdir:
            print("  DIR   %-52s" % (name + "/"))
        else:
            print("  FILE  %-52s %14s" % (name, human(size) if size.isdigit() else size))


def cmd_tree(f, path, depth):
    def rec(p, d, prefix=""):
        for name, size, isdir in listdir(f, p):
            if isdir:
                print("%s  [%s]" % (prefix, name))
                if d > 0:
                    rec(p.rstrip("/") + "/" + name, d - 1, prefix + "    ")
            else:
                print("%s  %-50s %12s" % (prefix, name,
                                          human(size) if size.isdigit() else size))
    print("== " + path)
    rec(path, depth)


def cmd_cat(f, remote):
    buf = io.BytesIO()
    f.retrbinary("RETR " + remote, buf.write, blocksize=256 * 1024)
    d = buf.getvalue()
    for enc in ("utf-8-sig", "utf-8", "gbk", "latin1"):
        try:
            print(d.decode(enc))
            return
        except UnicodeDecodeError:
            continue
    print(d[:2000].hex(" "))


def cmd_get(f, remote, local=None):
    local = local or os.path.basename(remote.rstrip("/"))
    buf = io.BytesIO()
    f.retrbinary("RETR " + remote, buf.write, blocksize=512 * 1024)
    d = buf.getvalue()
    with open(local, "wb") as fh:
        fh.write(d)
    print("已下载 %s  ->  %s" % (remote, local))
    print("  %d B  md5=%s  head=%s" % (len(d), hashlib.md5(d).hexdigest(), d[:8].hex(" ")))


def cmd_put(f, local, remote_dir, force=False):
    name = os.path.basename(local)
    ext = os.path.splitext(name)[1].lower()
    src = open(local, "rb").read()
    if ext in SIGNED_EXT and not force:
        print("!! 拒绝上传 %s" % name)
        print("   ftpsrv 对 SELF 有透明解密：上传后再取回来会变成裸 ELF，")
        print("   签名状态不受你控制。要改游戏内容请改用「PC 改目录 -> 重打包镜像 -> 传镜像」。")
        print("   （确实要传原始数据请加 --force，但要知道它不会被原样保留）")
        return 1
    if ext in SIGNED_EXT and force:
        print("!! --force：正在上传签名二进制 %s —— 签名可能被改写，后果自负。" % name)
    if src[:4] == bytes.fromhex("4f153d1d") or src[:4] == bytes.fromhex("5414f5ee"):
        print("!! 源文件是 SELF（magic %s）；FTP 写入后签名状态不可控。"
              % src[:4].hex(" "))
        if not force:
            print("   已中止。如确实要传，加 --force。")
            return 1

    remote = remote_dir.rstrip("/") + "/" + name
    with open(local, "rb") as fh:
        f.storbinary("STOR " + remote, fh, blocksize=512 * 1024)
    print("已上传 %s -> %s  (%d B)" % (local, remote, len(src)))

    # 回传校验（服务器报的大小不可信）
    buf = io.BytesIO()
    f.retrbinary("RETR " + remote, buf.write, blocksize=512 * 1024)
    back = buf.getvalue()
    same_size = len(back) == len(src)
    same_md5 = hashlib.md5(back).hexdigest() == hashlib.md5(src).hexdigest()
    print("  回传：%d B   md5=%s" % (len(back), hashlib.md5(back).hexdigest()))
    print("  源  ：%d B   md5=%s" % (len(src), hashlib.md5(src).hexdigest()))
    if same_md5:
        print("  >>> 校验通过：逐字节一致")
        return 0
    if same_size:
        print("  >>> ⚠️ 大小一致但 md5 不同 —— 可能被服务器改写过内容")
    else:
        print("  >>> ⚠️ 大小不一致（相差 %d B）—— 大概率被透明解密/重编码了"
              % (len(back) - len(src)))
        print("      取回文件 head=%s（4f153d1d=FSELF / 5414f5ee=正品SELF / 7f454c46=裸ELF）"
              % back[:4].hex(" "))
    return 1


def cmd_find(f, root, keyword, depth):
    kw = keyword.lower()
    hits = []

    def rec(p, d):
        if d < 0:
            return
        for name, size, isdir in listdir(f, p):
            full = p.rstrip("/") + "/" + name
            if kw in name.lower():
                hits.append((full, size, isdir))
            if isdir and d > 0:
                rec(full, d - 1)

    rec(root, depth)
    print("在 %s 下（深度 %d）匹配 '%s' 的条目：" % (root, depth, keyword))
    for full, size, isdir in hits:
        print("  %-70s %12s" % (full + ("/" if isdir else ""),
                                human(size) if size.isdigit() else size))
    if not hits:
        print("  (无)")


def main() -> int:
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd = a[0]
    force = "--force" in a
    a = [x for x in a if x != "--force"]

    try:
        f = connect()
    except Exception as e:
        print("连接 %s:%d 失败：%s" % (HOST, PORT, e), file=sys.stderr)
        return 2

    try:
        print("已连接 %s:%d（passive）" % (HOST, PORT))
        if cmd == "ls" and len(a) >= 2:
            cmd_ls(f, a[1])
        elif cmd == "tree" and len(a) >= 2:
            cmd_tree(f, a[1], int(a[2]) if len(a) > 2 else 2)
        elif cmd == "cat" and len(a) >= 2:
            cmd_cat(f, a[1])
        elif cmd == "get" and len(a) >= 2:
            cmd_get(f, a[1], a[2] if len(a) > 2 else None)
        elif cmd == "put" and len(a) >= 3:
            return cmd_put(f, a[1], a[2], force)
        elif cmd == "find" and len(a) >= 3:
            cmd_find(f, a[1], a[2], int(a[3]) if len(a) > 3 else 3)
        else:
            print(__doc__)
            return 2
    finally:
        try:
            f.quit()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
