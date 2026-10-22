#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把网络共享 / 本地目录下的 PS5 游戏目录，按中文游戏名归类到同名子目录。

同一卷内使用 os.rename（SMB 共享上是服务端改名），百 GB 级也是秒完成，不搬数据。

用法:
    python organize_nas_games.py "\\\\iStoreOS\\games"                 # 只报告，不动
    python organize_nas_games.py "\\\\iStoreOS\\games" --apply         # 真正执行
    python organize_nas_games.py "D:/ps5games" --apply --map zh.json  # 自定义名字表

--map 指向一个 JSON: {"PPSA02424-app": "双人成行", ...}，优先级最高。
未在名字表里的游戏，会从 sce_sys/param.json 读 titleName 作为「参考名」并跳过，
避免用英文/外语名建目录。
"""
import argparse
import json
import os
import re
import sys

TITLE_RE = re.compile(r'"titleName"\s*:\s*"([^"]+)"')


def read_title(game_dir):
    p = os.path.join(game_dir, "sce_sys", "param.json")
    if not os.path.exists(p):
        return None
    try:
        t = open(p, encoding="utf-8", errors="replace").read()
    except OSError:
        return None
    m = TITLE_RE.search(t)
    return m.group(1) if m else None


def count_files(path):
    return sum(len(f) for _, _, f in os.walk(path))


def is_app_dir(path):
    return (os.path.exists(os.path.join(path, "eboot.bin"))
            and os.path.exists(os.path.join(path, "sce_sys", "param.json")))


def find_app_dirs(root, max_depth=3):
    """找出目录里真正的 app 目录（含 eboot.bin + sce_sys/param.json）。"""
    hits = []
    for cur, dirs, _files in os.walk(root):
        depth = cur[len(root):].count(os.sep)
        if depth > max_depth:
            dirs[:] = []
            continue
        if is_app_dir(cur):
            hits.append(cur)
            dirs[:] = []      # 不再往下找
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base", help="游戏所在的共享/目录，例如 \\\\iStoreOS\\games")
    ap.add_argument("--apply", action="store_true", help="真正执行移动（默认只报告）")
    ap.add_argument("--map", dest="mapfile", help="自定义 目录名->中文名 的 JSON 映射")
    args = ap.parse_args()

    base = args.base
    if not os.path.isdir(base):
        sys.exit("[错误] 无法访问: " + base)

    mapping = {}
    if args.mapfile:
        mapping = json.load(open(args.mapfile, encoding="utf-8"))

    entries = sorted(d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d)))
    print("共 %d 个顶层目录\n" % len(entries))

    def has_cjk(s):
        return any("\u4e00" <= ch <= "\u9fff" for ch in s)

    todo, fine, warnings = [], [], []
    for d in entries:
        full = os.path.join(base, d)
        cn = mapping.get(d)
        title = read_title(full)
        if title is not None:
            # 顶层目录本身就是 app 目录 -> 需要包进中文名目录
            if cn is None:
                warnings.append((d, "无中文名映射；titleName=%r" % title))
            elif d == cn:
                fine.append((d, "已是中文名且为 app 目录"))
            else:
                todo.append((d, cn, title, count_files(full)))
            continue

        # 顶层不是 app 目录：往下找，判断是「已整理」还是「套了多层」
        inner = find_app_dirs(full)
        if not inner:
            warnings.append((d, "不是 app 目录（找不到 eboot.bin + sce_sys/param.json）"))
            continue
        if len(inner) > 1:
            warnings.append((d, "内部有 %d 个 app 目录，结构混乱，需人工确认" % len(inner)))
            continue
        rel = os.path.relpath(inner[0], full)
        depth = rel.count(os.sep)   # 0 = 直接子目录，>=1 = 多套了
        if depth == 0:
            if has_cjk(d):
                fine.append((d, "已整理好：中文名目录 / " + rel))
            else:
                warnings.append((d, "已是「父目录/app」结构但父目录不是中文名 -> 可直接改名"))
        else:
            warnings.append((d, "多套了 %d 层 -> %s（拷去 PS5 前需压平）" % (depth, rel)))

    for d, cn, title, n in todo:
        print("[计划] %-52s -> %s\\%s  (%d 文件, titleName=%r)" % (d, cn, d, n, title))
    if fine:
        print("\n[已就绪]")
        for d, why in fine:
            print("  %-52s %s" % (d, why))
    if warnings:
        print("\n[需人工确认]")
        for d, why in warnings:
            print("  %-52s %s" % (d, why))

    if not args.apply:
        print("\n（只报告模式，未做任何修改；加 --apply 执行）")
        return

    print("\n=== 执行 ===")
    for d, cn, title, n_before in todo:
        src = os.path.join(base, d)
        dst_dir = os.path.join(base, cn)
        os.makedirs(dst_dir, exist_ok=True)
        dst = os.path.join(dst_dir, d)
        if os.path.exists(dst):
            print("[跳过] 目标已存在:", dst)
            continue
        try:
            os.rename(src, dst)
        except OSError as e:
            print("[失败]", d, "->", cn, ":", e)
            continue
        n_after = count_files(dst)
        ok = n_after == n_before and is_app_dir(dst)
        print("[%s] %s -> %s\\%s  文件 %d->%d  app目录=%s"
              % ("完成" if ok else "警告", d, cn, d, n_before, n_after, is_app_dir(dst)))

    print("\n=== 结果结构 ===")
    for d in sorted(os.listdir(base)):
        p = os.path.join(base, d)
        if not os.path.isdir(p):
            continue
        subs = [x for x in os.listdir(p) if os.path.isdir(os.path.join(p, x))]
        if subs:
            print(d + "\\")
            for s in subs:
                flag = "  <-- app 目录" if is_app_dir(os.path.join(p, s)) else ""
                print("   └─ " + s + flag)
        else:
            print(d + "\\  (%d 项，无子目录)" % len(os.listdir(p)))


if __name__ == "__main__":
    main()
