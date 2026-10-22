#!/usr/bin/env python3
"""SMP (ShadowMountPlus) debug.log 解析器 —— 只依赖标准库。

作用：把 /data/shadowmount/debug.log 变成一条可读的启动时间线，并直接给出
     「静默挂起(hang)」还是「崩溃(crash)」的判读。这是排查「能启动但跑不起来」
     最快的第一步，比来回猜有效得多。

用法：
    python smp_log.py <debug.log> [--title PPSAxxxxx] [--all] [--json]

    --title PPSAxxxxx   只看这一个标题（推荐，日志里常混着别的游戏）
    --all               打印全部原始行，不只关键行
    --json              以 JSON 输出（便于后续处理）

判读逻辑（详见 references/runtime-diagnosis.md）：
    started → 60s 内 MDBG 报 expired 且无 error   => hang（静默挂起）
    started → 数秒内 MDBG 报 game error 0x...     => crash（进程被杀/缺库）
"""
from __future__ import annotations

import json
import re
import sys

# ---- 日志行分类 ----------------------------------------------------------
# ⚠️ 顺序与正则都很讲究：
#   * "monitoring expired" 行里含 "game error" 字样（"game error monitoring expired"），
#     若把 mdbg_error 写成宽泛的 `game error` 就会被误判成崩溃 —— 必须要求行内出现
#     真正的 8 位十六进制错误码（`0x........`）。
#   * mdbg_expired 放在 mdbg_error 之前，双保险。
PATTERNS = [
    ("mount",        re.compile(r"Mounting image", re.I)),
    ("fakelib_g",    re.compile(r"\[FAKELIB\].*game mounted", re.I)),
    ("fakelib_d",    re.compile(r"\[FAKELIB\].*directory mounted", re.I)),
    ("started",      re.compile(r"\[GAME\]\s*started", re.I)),
    ("mdbg_expired", re.compile(r"\[MDBG\].*monitoring expired", re.I)),
    ("mdbg_error",   re.compile(r"\[MDBG\].*game error.*0x[0-9a-fA-F]{8}", re.I)),
    ("mdbg_begin",   re.compile(r"\[MDBG\].*monitoring game errors", re.I)),
    ("stopped",      re.compile(r"game stopped|process exited|finalizing stopped", re.I)),
    ("cfg",          re.compile(r"\[CFG\]", re.I)),
    ("focus",        re.compile(r"AppFocus", re.I)),
    ("link",         re.compile(r"\[LINK\]", re.I)),
    ("reg",          re.compile(r"\[REG\]", re.I)),
    ("img",          re.compile(r"\[IMG\]", re.I)),
    ("err",          re.compile(r"\b(ERROR|FATAL|coredump|crash(?:ed)?)\b", re.I)),
]

# 出现过的错误码名（日志里通常自带括号名，这里只对个别已知码做补充说明）
ERR_HINT = {
    "0xa0020318": "SYSTEM_ABNORMAL_TERMINATION_REQUEST —— 进程被杀，"
                  "实测出现在「完全缺 fakelib」的情况下（6 秒即死）",
    "0x80020001": "常见 SCE 通用错误",
}

TS = re.compile(r"\[(\d{2}:\d{2}:\d{2}(?:\.\d+)?)\]|^\s*(\d{2}:\d{2}:\d{2}(?:\.\d+)?)")
CODE = re.compile(r"0x[0-9a-fA-F]{8}")
LAYERS = re.compile(r"layers\s*=\s*(\d+)", re.I)


def get_ts(line: str):
    """SMP 日志的时间戳通常写成 `[21:48:01]`，也可能在行首裸写。"""
    m = TS.search(line)
    if not m:
        return None
    return m.group(1) or m.group(2)


def classify(line: str) -> str | None:
    for kind, pat in PATTERNS:
        if pat.search(line):
            return kind
    return None


def main() -> int:
    args = [a for a in sys.argv[1:]]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0

    path = args[0]
    title = None
    show_all = False
    as_json = False
    i = 1
    while i < len(args):
        a = args[i]
        if a == "--title" and i + 1 < len(args):
            title = args[i + 1].upper(); i += 2; continue
        if a == "--all":
            show_all = True; i += 1; continue
        if a == "--json":
            as_json = True; i += 1; continue
        print("未知参数:", a, file=sys.stderr)
        return 2

    with open(path, "rb") as fh:
        text = fh.read().decode("utf-8", "replace")
    lines = text.splitlines()

    events = []
    for n, line in enumerate(lines, 1):
        if title and title not in line.upper():
            continue
        kind = classify(line)
        if kind or show_all:
            events.append({
                "line": n,
                "kind": kind or "raw",
                "ts": get_ts(line),
                "text": line.strip(),
            })

    if as_json:
        print(json.dumps({"file": path, "total_lines": len(lines),
                          "title_filter": title, "events": events},
                         ensure_ascii=False, indent=1))
        return 0

    print("=" * 78)
    print("SMP debug.log 解析   %s" % path)
    print("  总行数 %d   标题过滤 %s   关键事件 %d 条"
          % (len(lines), title or "(无)", len(events)))
    print("=" * 78)

    MARK = {
        "mount": "▸", "fakelib_g": "★", "fakelib_d": "·",
        "started": "▶", "mdbg_begin": " ", "mdbg_error": "✖",
        "mdbg_expired": "…", "stopped": "■", "cfg": "¤",
        "focus": " ", "link": " ", "reg": " ", "img": " ", "err": "!",
        "raw": " ",
    }

    # 按「启动周期」切分：每个 [GAME] started 开启一个新周期
    cycles: list[dict] = []
    cur = None
    for ev in events:
        k = ev["kind"]
        if k == "started":
            cur = {"start": ev, "error": None, "expired": None, "stopped": None}
            cycles.append(cur)
        elif cur is not None:
            if k == "mdbg_error" and cur["error"] is None:
                cur["error"] = ev
            elif k == "mdbg_expired" and cur["expired"] is None:
                cur["expired"] = ev
            elif k == "stopped" and cur["stopped"] is None:
                cur["stopped"] = ev

    for ev in events:
        k = ev["kind"]
        ts = ev["ts"] or "        "
        print("%s %5d| %s  %s" % (MARK.get(k, " "), ev["line"], ts, ev["text"][:200]))
        if k == "mdbg_error":
            for c in sorted(set(CODE.findall(ev["text"]))):
                if c.lower() in ERR_HINT:
                    print("        └─ %s : %s" % (c, ERR_HINT[c.lower()]))
        if k == "stopped":
            m = LAYERS.search(ev["text"])
            if m:
                print("        └─ layers=%s（挂载层数；比正常少说明少挂了一层东西）"
                      % m.group(1))

    print()
    print("-" * 78)
    print("启动周期（每个 [GAME] started 为一个周期）")
    print("-" * 78)
    if not cycles:
        print("  (没有找到任何 [GAME] started)")
    for i, c in enumerate(cycles, 1):
        s = c["start"]
        desc = "启动后无后续记录（可能还在跑，或日志被截断）"
        kind = None
        if c["error"]:
            codes = " ".join(sorted(set(CODE.findall(c["error"]["text"])))) or "?"
            desc = "✖ 崩溃  %s @%s" % (codes, c["error"]["ts"] or "?")
            kind = "crash"
        elif c["expired"]:
            desc = "… 60 秒内 0 条错误（expired @%s）→ 静默挂起" % (c["expired"]["ts"] or "?")
            kind = "hang"
        tail = ""
        if c["stopped"]:
            m = LAYERS.search(c["stopped"]["text"])
            tail = "   [结束 @%s%s]" % (c["stopped"]["ts"] or "?",
                                        " layers=%s" % m.group(1) if m else "")
        print("  周期 %-3d  启动 @%-12s  %s%s"
              % (i, s["ts"] or "?", desc, tail))

    print()
    print("-" * 78)
    print("判读（以**最后一个周期**为准）")
    print("-" * 78)
    if not cycles:
        print("  → 没有启动记录。确认 --title 过滤是否正确，或日志已滚动到 debug.log.1")
    else:
        c = cycles[-1]
        if c["error"]:
            codes = " ".join(sorted(set(CODE.findall(c["error"]["text"]))))
            print("  → 判读：**崩溃 (crash)**，错误码 %s。看上面 ✖ 行。" % codes)
            for code in sorted(set(CODE.findall(c["error"]["text"]))):
                if code.lower() in ERR_HINT:
                    print("     %s : %s" % (code, ERR_HINT[code.lower()]))
            print("     若为 0xa0020318 且日志里没有 [FAKELIB] game mounted，"
                  "多半是缺必需库（fakelib 被删）—— fakelib 是必需品，放回去。")
        elif c["expired"]:
            print("  → 判读：**静默挂起 (hang)**。60 秒内 SMP 崩溃监视器一条错误都没报。")
            print("     病因几乎一定在运行期（资源加载 / 等待 / 渲染），不在签名或挂载层。")
            print("     ⚠️ 但 expired ≠ 死锁！要看 [GAME] started 之后进程还活了多久：")
            print("        活了十几分钟 = 它在**慢慢爬 (crawl)**，不是卡死，继续等/盯进度条；")
            print("        超过 8~10 分钟完全不动，才是真卡住。")
            print("     下一步见 references/runtime-diagnosis.md：")
            print("       §14 ★图形栈三方对比（第一嫌疑）  §6 fakelib（存在≠干净）")
            print("       §4 Unity/Addressables  §5 SMP 配置项  §7 boot.config 显示请求")
            print("     ⚠️ 判定前先确认等了足够久：实测走完 logo 就要约 1 分钟，")
            print("        首次加载 1.5 GB 资源可能要 5 分钟。")
        else:
            print("  → 判读：**信息不足**——已启动，但之后既无 error 也无 expired 行。")
            print("     多半是进程还在跑（60 秒监视期未到就取日志了）。等一会儿重新取。")

    print()
    print("提示：换版本后请重新取日志，并确认 [CFG] 行里的 fakelib_rules 是否为预期值；")
    print("      fakelib_rules=0 表示没有任何按游戏的假库规则生效。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
