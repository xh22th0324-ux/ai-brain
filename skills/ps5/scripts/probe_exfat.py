"""exFAT 镜像深度诊断（只读，不依赖 ps5-dump-forge）。

比 `forge.py verify` 更进一步：verify 只看几何/卷标/根目录有没有 eboot，
本脚本会把**整个目录树**走一遍，并统计：

  * 每个可执行文件（eboot.bin / *.prx / *.sprx / *.self）的 **SELF 魔数** ——
    判断这份镜像是「安装用正品签名（54 14 F5 EE）」还是「侧载就绪 FSELF（4F 15 3D 1D）」
  * 侧载层的关键文件是否存在（ampr_emu.index / fakelib / license.dat /
    nptitle.dat / playgo-*.dat / npbind.dat …）
  * sce_sys 的完整清单

用法:
    python probe_exfat.py <镜像路径> [--all]

排查「镜像能挂载但游戏起不来」时，最有价值的做法是：
把**你自己做的镜像**和**一个已知能正常跑的镜像**分别跑一遍，
对比两项 —— ① SELF 魔数分布，② 侧载层文件清单。
两者魔数分布不一致，基本就能定位问题。

排查 PS5 游戏启动失败时与 `forge.py verify` 搭配使用。
"""
import struct
import sys

MAGICS = {
    bytes.fromhex("5414f5ee"): "正品签名(安装用)",
    bytes.fromhex("4f153d1d"): "FSELF(侧载就绪)",
    bytes.fromhex("7f454c46"): "裸ELF",
    bytes.fromhex("504b0304"): "ZIP",
}

EXTS = ('.bin', '.prx', '.sprx', '.self', '.elf')

SIDELOAD_KEYS = [
    'ampr_emu.index', 'fakelib', 'fakelib/libSceAmpr.sprx',
    'fakelib/libSceNpEntitlementAccess.sprx',
    'sce_sys/license.dat', 'sce_sys/license.info', 'sce_sys/nptitle.dat',
    'sce_sys/disc_info.dat',
    'sce_sys/playgo-chunk.dat', 'sce_sys/playgo-ficm.dat',
    'sce_sys/playgo-hash-table.dat',
    'sce_sys/uds/npbind.dat', 'sce_sys/trophy2/npbind.dat',
    'sce_sys/param.json', 'sce_sys/origin-param.json', 'sce_sys/target-param.json',
]


class ExFat:
    """最小可用的 exFAT 只读解析器。"""

    def __init__(self, path):
        self.f = open(path, 'rb')
        self.path = path
        bs = self.f.read(512)
        if bs[3:11] != b'EXFAT   ':
            raise SystemExit(f"不是 exFAT 镜像: 文件系统名 = {bs[3:11]!r}")
        self.part_off, self.vol_len = struct.unpack_from('<QQ', bs, 0x40)
        self.fat_off, self.fat_len = struct.unpack_from('<II', bs, 0x50)
        self.heap_off, self.cluster_cnt = struct.unpack_from('<II', bs, 0x58)
        self.root_clu = struct.unpack_from('<I', bs, 0x60)[0]
        self.serial = struct.unpack_from('<I', bs, 0x64)[0]
        self.fs_rev = struct.unpack_from('<H', bs, 0x68)[0]
        self.sector = 1 << bs[0x6C]
        self.cluster = self.sector << bs[0x6D]
        self.nfats = bs[0x6E]
        self._fat = None
        self._label = None

    def fat(self, i):
        if self._fat is None:
            self.f.seek(self.fat_off * self.sector)
            self._fat = self.f.read(self.fat_len * self.sector)
        return struct.unpack_from('<I', self._fat, i * 4)[0]

    def chain(self, s):
        out, c, seen = [], s, set()
        while 2 <= c < 0xFFFFFFF8 and c not in seen:
            out.append(c)
            seen.add(c)
            if len(out) > 8_000_000:
                break
            c = self.fat(c)
        return out

    def cluster_data(self, c):
        self.f.seek(self.heap_off * self.sector + (c - 2) * self.cluster)
        return self.f.read(self.cluster)

    def read_dir(self, start):
        """返回 [(name, is_dir, size, first_cluster), ...]"""
        data = b''.join(self.cluster_data(c) for c in self.chain(start))
        out, i = [], 0
        while i < len(data) and data[i] != 0x00:
            if data[i] == 0x83:                     # 卷标签
                n = data[i + 1]
                self._label = data[i + 2:i + 2 + n * 2].decode('utf-16-le', 'replace')
                i += 32
                continue
            if data[i] == 0x85:                     # 文件目录项
                sec = data[i + 1]
                attr = struct.unpack_from('<H', data, i + 4)[0]
                name, size, first = '', 0, 0
                for k in range(1, sec + 1):
                    e = data[i + k * 32:i + (k + 1) * 32]
                    if len(e) < 32:
                        break
                    if e[0] == 0xC0:
                        first = struct.unpack_from('<I', e, 20)[0]
                        size = struct.unpack_from('<Q', e, 24)[0]
                    elif e[0] == 0xC1:
                        for j in range(0, 30, 2):
                            ch = struct.unpack_from('<H', e, 2 + j)[0]
                            if ch:
                                name += chr(ch)
                out.append((name, bool(attr & 0x10), size, first))
                i += 32 * (sec + 1)
                continue
            i += 32
        return out

    def walk(self, start=None, prefix=''):
        """递归遍历，产出 (path, is_dir, size, first_cluster)。"""
        root = self.root_clu if start is None else start
        for name, isdir, size, first in self.read_dir(root):
            p = f"{prefix}/{name}"
            if isdir:
                yield (p, True, 0, first)
                yield from self.walk(first, p)
            else:
                yield (p, False, size, first)

    def head(self, first, n=8):
        """读某个文件的前 n 字节（按首簇定位，不跟链）。"""
        if first < 2:
            return b''
        self.f.seek(self.heap_off * self.sector + (first - 2) * self.cluster)
        return self.f.read(n)

    def read_file(self, path):
        """按路径读取整个文件（小文件用；大文件慎用）。"""
        parts = [p for p in path.strip('/').split('/') if p]
        cur = self.root_clu
        for i, p in enumerate(parts):
            ent = {n: (d, s, f) for n, d, s, f in self.read_dir(cur)}
            if p not in ent:
                return None
            d, s, f = ent[p]
            if i == len(parts) - 1:
                return b''.join(self.cluster_data(c) for c in self.chain(f))[:s]
            cur = f
        return None


def magic_of(b):
    if len(b) < 4:
        return '<空>'
    return MAGICS.get(b[:4], b[:4].hex(' '))


def probe(path, show_all=False):
    ex = ExFat(path)
    print("=" * 92)
    print(f"### {path}")
    print("=" * 92)
    print(f"  扇区 / 簇     : {ex.sector} B / {ex.cluster} B ({ex.cluster // 1024} KiB)")
    print(f"  卷容量        : {ex.vol_len * ex.sector / 1024**3:.2f} GiB   FAT数={ex.nfats}")
    print(f"  簇总数        : {ex.cluster_cnt}   根目录首簇={ex.root_clu}  rev=0x{ex.fs_rev:04x}")

    allitems = list(ex.walk())
    files = [x for x in allitems if not x[1]]
    total = sum(x[2] for x in files)
    print(f"  文件总数      : {len(files)}   合计 {total:,} B ({total / 1024**3:.2f} GiB)")
    print(f"  卷标签        : {ex._label!r}")

    print("\n  --- 顶层条目 ---")
    for name, isdir, size, first in ex.read_dir(ex.root_clu):
        if isdir:
            n = sum(1 for x in ex.walk(first) if not x[1])
            print(f"    [DIR ] {name:<24} ({n} 文件)")
        else:
            print(f"    [FILE] {name:<24} {size:>15,}  首簇={first}")

    fmap = {p.lstrip('/'): (s, first) for p, isdir, s, first in files}
    dmap = {p.lstrip('/') for p, isdir, s, first in allitems if isdir}
    print("\n  --- 侧载层关键文件 ---")
    for k in SIDELOAD_KEYS:
        if k in dmap:
            print(f"    [有] {k}/")
        elif k in fmap:
            s, first = fmap[k]
            print(f"    [有] {k:<42} {s:>12,}  首4字节={magic_of(ex.head(first))}")
        else:
            print(f"    [无] {k}")

    print("\n  --- 可执行文件 SELF 魔数统计 ---")
    stat = {}
    for p, isdir, size, first in files:
        if p.lower().endswith(EXTS):
            stat.setdefault(magic_of(ex.head(first)), []).append((p, size))
    for m, lst in sorted(stat.items(), key=lambda x: -len(x[1])):
        print(f"    {m:<24} x{len(lst)}")
    print(f"    可执行文件合计 {sum(len(v) for v in stat.values())} 个")

    if show_all:
        print("\n  --- 逐个明细 ---")
        for m, lst in stat.items():
            for p, s in sorted(lst):
                print(f"      {m:<24} {s:>13,}  {p}")

    print("\n  --- sce_sys 内容 ---")
    for name, isdir, size, first in ex.read_dir(ex.root_clu):
        if name == 'sce_sys' and isdir:
            for n2, d2, s2, f2 in ex.read_dir(first):
                if d2:
                    print(f"    [DIR ] {n2}/  -> {sorted(x[0] for x in ex.read_dir(f2))}")
                else:
                    print(f"    [FILE] {n2:<34} {s2:>12,}")


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    probe(sys.argv[1], show_all='--all' in sys.argv)


if __name__ == '__main__':
    main()
