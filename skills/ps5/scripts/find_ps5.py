#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在局域网里用「端口指纹」定位 PS5。

PS5 越狱环境常同时开着这几样服务，组合起来几乎是主机独有的指纹：
    2121  ftpsrv (etaHEN)
    8770  PS4Mount 面板
    8888  web-file-manager
    9100  ps5-exporter
    9021  elfldr
主机 DHCP 换 IP 后，原来的书签/脚本全部连不上，用本脚本重新找回。

用法:
    python find_ps5.py                       # 自动取本机网段，扫 2121/8770/8888
    python find_ps5.py <PRIVATE_IP>/24
    python find_ps5.py <PRIVATE_IP>/24 --ports 2121,8770,8888,9100
    python find_ps5.py --expect 2121         # 只认「某端口必定开着」的地址
"""
import argparse
import concurrent.futures as cf
import ipaddress
import socket
import sys

DEFAULT_PORTS = (2121, 8770, 8888)


def probe(ip, ports, timeout):
    hits = []
    for p in ports:
        s = socket.socket()
        s.settimeout(timeout)
        try:
            s.connect((str(ip), p))
            hits.append(p)
        except OSError:
            pass
        finally:
            s.close()
    return (str(ip), hits) if hits else None


def local_subnet():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))          # 不发包，只为拿到出口网卡地址
        ip = s.getsockname()[0]
    except OSError:
        ip = "<PRIVATE_IP>"
    finally:
        s.close()
    return ipaddress.ip_network(ip + "/24", strict=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("subnet", nargs="?", help="网段，如 <PRIVATE_IP>/24；省略则自动识别")
    ap.add_argument("--ports", default=",".join(map(str, DEFAULT_PORTS)))
    ap.add_argument("--expect", type=int, help="要求该端口必须开放才算命中（如 2121）")
    ap.add_argument("--timeout", type=float, default=0.4)
    ap.add_argument("--workers", type=int, default=80)
    args = ap.parse_args()

    net = ipaddress.ip_network(args.subnet, strict=False) if args.subnet else local_subnet()
    ports = [int(x) for x in args.ports.split(",") if x.strip()]
    hosts = [h for h in net.hosts()]
    print("扫描 %s，端口 %s，共 %d 个地址\n" % (net, ports, len(hosts)))

    found = []
    with cf.ThreadPoolExecutor(args.workers) as ex:
        for r in ex.map(lambda ip: probe(ip, ports, args.timeout), hosts):
            if not r:
                continue
            ip, hits = r
            if args.expect and args.expect not in hits:
                continue
            found.append((ip, hits))

    if not found:
        print("没有命中。检查：主机是否开机、是否同一网段、防火墙/AP 隔离是否拦截。")
        sys.exit(1)

    for ip, hits in found:
        tag = ""
        if 2121 in hits and 8770 in hits:
            tag = "  <-- 很像 PS5（ftpsrv + PS4Mount）"
        elif 8888 in hits:
            tag = "  <-- 有 web-file-manager"
        print("%-16s 开放 %s%s" % (ip, hits, tag))

    print("\n下一步：")
    print("  curl http://<IP>:8888/          # 验证 web-file-manager")
    print("  curl http://<IP>:8770/api/games # 验证 PS4Mount")
    print("根治办法：在路由器里按 PS5 的 MAC 做静态 DHCP 绑定。")


if __name__ == "__main__":
    main()
