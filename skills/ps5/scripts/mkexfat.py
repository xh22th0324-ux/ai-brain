#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mkexfat.py —— 把一个目录里的文件收拾成「整盘 exFAT 镜像」（.img）。

适用场景：手里是一堆**原样放进去就能用**的文件（例如 PS4 fake pkg 给 PS4Mount 用），
不能用 ps5-dump-forge 转换，但想要一个「写盘即用、布局不会错」的单文件镜像。

做法：Windows 自带 diskpart 建 fixed VHD -> 建 MBR 分区 -> 格式化成 exFAT ->
      复制文件 -> 卸载 -> 剥掉 VHD 尾部 512B footer 得到裸 .img。

要求：管理员权限（diskpart 需要）；Windows；无需 Hyper-V 或第三方工具。

用法：
    python mkexfat.py <源目录> <输出.img> [--label 卷标] [--mb 8192]
                      [--clu 65536] [--letter U] [--keep-dirs] [--bare PATH]

    --mb        卷大小(MB)。省略时按内容自动算（内容 x1.25 + 64MB，向上取整到 64MB）
    --clu       簇大小(字节)，默认 65536（64 KiB，社区推荐值）
    --letter    临时盘符，默认自动挑一个空闲的
    --keep-dirs 保留源目录里的子目录结构（默认只把顶层文件铺到镜像根目录）
    --bare      额外导出一份「裸 exFAT 文件系统」镜像到 PATH。
                ⚠️ 两种形态用途不同：
                  整盘 .img  = MBR + 分区，用于**写到 U 盘/移动硬盘**当磁盘用；
                  裸 .exfat  = 偏移 0 直接是 exFAT 引导扇区、无分区表，
                               这是 ShadowMountPlus 期望的镜像形态（游戏文件在镜像根目录）。
                同一份卷可以同时导出两种，别搞混。
"""
import os
import shutil
import string
import struct
import subprocess
import sys
import tempfile
import time

FOOTER = 512


def free_letters():
    out = []
    for L in string.ascii_uppercase:
        if not os.path.exists(L + ":\\"):
            out.append(L)
    return out


def run_diskpart(script_text, tag):
    fd, path = tempfile.mkstemp(suffix=".txt", prefix="dpscript_")
    os.close(fd)
    with open(path, "w", encoding="ascii") as f:
        f.write(script_text)
    try:
        p = subprocess.run(["diskpart", "/s", path], capture_output=True)
        out = (p.stdout or b"") + (p.stderr or b"")
        txt = out.decode("utf-8", "replace")
        # diskpart 输出常是 OEM 代码页
        if "DiskPart" not in txt and "磁盘" not in txt:
            try:
                txt = out.decode("mbcs", "replace")
            except Exception:
                pass
        if p.returncode != 0:
            raise RuntimeError("diskpart 失败 (exit %d)\n%s" % (p.returncode, txt))
        return txt
    finally:
        try:
            os.remove(path)
        except Exception:
            pass


def vol_geometry(letter):
    r"""直接读裸卷设备（卷盘符的设备名）的引导扇区，确认几何参数。"""
    import ctypes
    k32 = ctypes.windll.kernel32
    k32.CreateFileW.restype = ctypes.c_void_p
    h = k32.CreateFileW("\\\\.\\%s:" % letter, 0x80000000, 3, None, 3, 0, None)
    if not h or h == ctypes.c_void_p(-1).value:
        raise RuntimeError("打不开 \\\\.\\%s: (err %d)" % (letter, ctypes.get_last_error()))
    buf = ctypes.create_string_buffer(512)
    got = ctypes.c_ulong(0)
    k32.ReadFile(ctypes.c_void_p(h), buf, 512, ctypes.byref(got), None)
    k32.CloseHandle(ctypes.c_void_p(h))
    bs = buf.raw[:512]
    bpc = 1 << bs[0x6C]
    spc = 1 << bs[0x6D]
    return {
        "oem": bs[3:11],
        "bytes_per_sector": bpc,
        "sectors_per_cluster": spc,
        "cluster": bpc * spc,
        "clusters": struct.unpack("<I", bs[0x5C:0x60])[0],
        "vol_sectors": struct.unpack("<Q", bs[0x48:0x50])[0],
    }


def main():
    args = [a for a in sys.argv[1:]]
    opts = {"--label": None, "--mb": None, "--clu": "65536", "--letter": None,
            "--keep-dirs": False, "--bare": None}
    pos = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in opts:
            if a == "--keep-dirs":
                opts[a] = True
                i += 1
            else:
                opts[a] = args[i + 1]
                i += 2
        else:
            pos.append(a)
            i += 1
    if len(pos) != 2:
        print(__doc__)
        return 2

    src, out_img = os.path.abspath(pos[0]), os.path.abspath(pos[1])
    if not os.path.isdir(src):
        print("源目录不存在:", src)
        return 2
    if os.path.exists(out_img):
        print("输出已存在，先删掉:", out_img)
        return 2

    out_dir = os.path.dirname(out_img)
    os.makedirs(out_dir, exist_ok=True)
    vhd = out_img + ".vhd"

    # 统计内容大小
    items = sorted(os.listdir(src))
    files = []
    for it in items:
        p = os.path.join(src, it)
        if os.path.isfile(p):
            files.append((it, p, os.path.getsize(p), False))
        elif os.path.isdir(p):
            tot = sum(os.path.getsize(os.path.join(dp, f))
                      for dp, dn, fn in os.walk(p) for f in fn)
            files.append((it, p, tot, True))
    used = sum(x[2] for x in files)
    if used == 0:
        print("源目录是空的")
        return 2

    if opts["--mb"]:
        mb = int(opts["--mb"])
    else:
        need = used * 1.25 + 64 * 1024 * 1024
        mb = int((need + 64 * 1024 * 1024 - 1) // (64 * 1024 * 1024) * 64)
    if mb * 1024 * 1024 < used * 1.05:
        print("容量太小: 需要至少 %d MB" % (used * 1.05 / 1024 / 1024))
        return 2

    label = (opts["--label"] or os.path.basename(os.path.dirname(out_img)) or "DATA")[:11]
    clu = int(opts["--clu"])
    letter = opts["--letter"]
    if not letter:
        cands = [L for L in free_letters() if L not in ("A", "B")]
        if not cands:
            print("没有空闲盘符")
            return 2
        letter = cands[len(cands) // 2]

    print("源目录   : %s" % src)
    print("内容     : %d 项, %.3f GiB" % (len(files), used / 1024 ** 3))
    print("输出镜像 : %s  (%d MB, exFAT, 簇 %d B, 卷标 %s, 临时盘符 %s:)"
          % (out_img, mb, clu, label, letter))

    t0 = time.time()
    script = (
        'create vdisk file="%s" maximum=%d type=fixed\n'
        'select vdisk file="%s"\n'
        'attach vdisk\n'
        'create partition primary\n'
        'format fs=exfat unit=%d quick label=%s\n'
        'assign letter=%s\n' % (vhd, mb, vhd, clu, label, letter)
    )
    print("--- diskpart 建盘 ---")
    print(run_diskpart(script, "create"))

    ok = False
    try:
        if not os.path.exists(letter + ":\\"):
            raise RuntimeError("盘符 %s: 没有出现" % letter)
        g = vol_geometry(letter)
        print("几何确认 : OEM=%r  %d B 扇区 x %d = %d B/簇  簇数=%d  卷 %.3f GiB"
              % (g["oem"], g["bytes_per_sector"], g["sectors_per_cluster"],
                 g["cluster"], g["clusters"], g["vol_sectors"] * g["bytes_per_sector"] / 1024 ** 3))
        if g["oem"] != b"EXFAT   ":
            raise RuntimeError("不是 exFAT")

        print("--- 复制文件 ---")
        for name, path, sz, isdir in files:
            if isdir and opts["--keep-dirs"]:
                dst = os.path.join(letter + ":\\", name)
                shutil.copytree(path, dst)
                print("  [目录] %-58s %13d B" % (name, sz))
            elif isdir:
                # 摊平：把子目录里的文件铺到根目录
                for dp, dn, fn in os.walk(path):
                    for f in fn:
                        s = os.path.join(dp, f)
                        shutil.copyfile(s, os.path.join(letter + ":\\", f))
                        print("  %-60s %13d B" % (f[:60], os.path.getsize(s)))
            else:
                shutil.copyfile(path, os.path.join(letter + ":\\", name))
                d = os.path.getsize(os.path.join(letter + ":\\", name))
                print("  %-60s %13d B  %s" % (name[:60], d, "OK" if d == sz else "!!大小不符!!"))
        ok = True
    finally:
        print("--- diskpart 卸盘 ---")
        try:
            run_diskpart('select vdisk file="%s"\ndetach vdisk\n' % vhd, "detach")
        except Exception as e:
            print("卸盘失败:", e)
            print("手动处理: diskpart -> select vdisk file=\"%s\" -> detach vdisk" % vhd)
            return 3

    if not ok:
        return 3

    # 剥 footer
    vsz = os.path.getsize(vhd)
    with open(vhd, "rb") as f:
        f.seek(vsz - FOOTER)
        foot = f.read(FOOTER)
    if foot[:8] != b"conectix":
        print("警告: VHD 尾部不是 conectix footer，可能不是 fixed VHD。保留 .vhd 不删。")
        return 3
    disk_sz = vsz - FOOTER

    # ---- 额外导出「裸 exFAT 文件系统」（ShadowMountPlus 期望的形态）----
    bare_path = opts["--bare"]
    if bare_path:
        with open(vhd, "rb") as f:
            mbr = f.read(512)
        if mbr[510:512] != b"\x55\xaa":
            print("警告: 找不到 MBR，跳过导出裸文件系统")
        else:
            s_lba = struct.unpack("<I", mbr[454:458])[0]
            s_cnt = struct.unpack("<I", mbr[458:462])[0]
            with open(vhd, "rb") as fi, open(bare_path, "wb") as fo:
                fi.seek(s_lba * 512)
                left = s_cnt * 512
                while left > 0:
                    b = fi.read(min(8 * 1024 * 1024, left))
                    if not b:
                        break
                    fo.write(b)
                    left -= len(b)
            with open(bare_path, "rb") as f:
                vbr = f.read(16)
            bsz = os.path.getsize(bare_path)
            print("裸文件系统 : %s  %d B (%.3f GiB)  偏移0=%s  VBR@0=%s"
                  % (bare_path, bsz, bsz / 1024 ** 3, vbr[:4].hex(" "),
                     "OK" if vbr[3:11] == b"EXFAT   " else "⚠ 不是 exFAT"))
            print("             （无分区表、偏移 0 即引导扇区；给 SMP 这类镜像挂载用）")

    with open(vhd, "rb") as fi, open(out_img, "wb") as fo:
        left = disk_sz
        while left > 0:
            b = fi.read(min(8 * 1024 * 1024, left))
            if not b:
                break
            fo.write(b)
            left -= len(b)
    os.remove(vhd)
    print("--- 完成 ---")
    print("裸镜像   : %s  (%d B = %.3f GiB)"
          % (out_img, os.path.getsize(out_img), os.path.getsize(out_img) / 1024 ** 3))
    print("耗时     : %.1f 秒" % (time.time() - t0))
    print("下一步   : 用 Rufus / balenaEtcher / Win32DiskImager 写盘（会清空目标盘）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
