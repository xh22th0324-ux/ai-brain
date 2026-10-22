#!/usr/bin/env python3
"""USB / 内置盘读取吞吐实测（走 FTP，不需要任何主机端载荷）。

为什么用 FTP 测：
  13.60 上 ps5-payload-sdk 编的基准测试载荷（hwinfo_bench 等）跑不起来，
  见 references/env-1360-jailbreak.md。而 ftpsrv 是常驻的，读盘路径一样，
  只要「内置 SSD 对照能跑满千兆」就说明网络不是瓶颈，U 盘数字可信。

判读：
  ~35-40 MB/s   → USB 2.0 档位（PS5 前置 USB-A 就是 2.0 口）
  ~110 MB/s     → 已顶到千兆网天花板，说明 U 盘本身更快，网络才是瓶颈
  两者相差 3 倍 → 典型的「U 盘插错口」

用法：
  python usb_speed.py --path /mnt/usb0/ps4/CUSA15884/patch.pkg \\
      --offset-mb 1500 --size-mb 300 \\
      --control /data/homebrew/PPSA14708.exfat --control-offset-mb 20000

⚠️ offset 一定要取一个**之前没读过**的位置，否则命中主机的页缓存，数字会虚高。
"""
import argparse
import time
from ftplib import FTP

MB = 1024 * 1024


def measure(host, port, user, password, path, offset, size, label, timeout=30):
    ftp = FTP()
    ftp.connect(host, port, timeout=timeout)
    ftp.login(user, password)
    ftp.voidcmd('TYPE I')
    t0 = time.time()
    got = 0
    try:
        conn = ftp.transfercmd('RETR ' + path, rest=offset)
        while got < size:
            b = conn.recv(262144)
            if not b:
                break
            got += len(b)
        conn.close()
    except Exception as e:
        print('  recv stopped:', e)
    try:
        ftp.voidresp()
    except Exception:
        pass
    dt = time.time() - t0
    ftp.close()

    if not got or dt <= 0:
        print('%-42s no data' % label)
        return None
    mbps = got / MB / dt
    print('%-42s %8.1f MB / %6.2f s = %6.1f MB/s' % (label, got / MB, dt, mbps))
    return mbps


def verdict(mbps):
    if mbps is None:
        return ''
    if mbps < 50:
        return '  -> USB 2.0 档位（换到背面 USB-A 再测一次）'
    if mbps > 95:
        return '  -> 已顶到千兆网天花板，U 盘肯定比这更快'
    return '  -> 介于两者之间，可能受 U 盘自身性能限制'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--host', default='<PRIVATE_IP>')
    ap.add_argument('--port', type=int, default=2121)
    ap.add_argument('--user', default='anonymous')
    ap.add_argument('--password', default='')
    ap.add_argument('--path', required=True, help='要测的文件（通常在 /mnt/usbN 上）')
    ap.add_argument('--offset-mb', type=int, default=1500, help='起始偏移(MB)，避开缓存')
    ap.add_argument('--size-mb', type=int, default=300)
    ap.add_argument('--control', default='', help='对照组文件（内置 SSD 上的大文件）')
    ap.add_argument('--control-offset-mb', type=int, default=20000)
    a = ap.parse_args()

    size = a.size_mb * MB
    r1 = measure(a.host, a.port, a.user, a.password,
                 a.path, a.offset_mb * MB, size, 'USB @%d MB' % a.offset_mb)
    # 同一文件换个更深的偏移再测一次，排除端口抖动
    r2 = measure(a.host, a.port, a.user, a.password,
                 a.path, (a.offset_mb + 500) * MB, size,
                 'USB @%d MB (2nd pass)' % (a.offset_mb + 500))
    print('   ' + verdict(r1))

    if a.control:
        r3 = measure(a.host, a.port, a.user, a.password,
                     a.control, a.control_offset_mb * MB, size,
                     'internal SSD (control)')
        if r1 and r3 and r1 < r3 * 0.6:
            print('\n结论：U 盘明显慢于内置盘 —— 先换到背面 USB-A 口再测一次；')
            print('      若换口后仍慢，瓶颈在 U 盘自身（USB 2.0 盘或性能差）。')
        elif r1 and r3:
            print('\n结论：两者接近 => U 盘不是瓶颈，都卡在千兆网上限。')


if __name__ == '__main__':
    main()
