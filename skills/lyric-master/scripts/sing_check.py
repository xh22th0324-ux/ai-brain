# -*- coding: utf-8 -*-
"""sing_check.py — 词稿「可唱性」体检器（lyric-master / L3·L4）

FILE_VERSION = "v1.0"

它回答一个问题：**这份词，唱出来会不会糊、会不会拗口、会不会一眼看出机器味？**

和「字数够不够、能不能排进片子」无关 —— 那是排片的事。这里查的全是**耳朵能听出来的毛病**：
辙口散没散、齿音堆没堆、句尾憋不憋气、叠字会不会被吞、有没有一股套话味。

用法：
    python sing_check.py 词稿.txt
    python sing_check.py 词稿.txt --out ./out

词稿格式（段落标记可选）：
    【主歌】
    一句一行
    【副歌】
    一句一行

产出：
    可唱性体检报告.html   末字辙口分布 + 各项评分 + 逐条改法
    体检清单.txt          纯文本版，方便贴给研讨引擎当约束条件
"""
from __future__ import annotations

import argparse
import html
import io
import os
import re
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

FILE_VERSION = 'v1.0'

_TAG_RE = re.compile(r'^\s*[【\[（(]([^】\]）)]{1,10})[】\]）)]\s*(.*)$')
_CJK_RE = re.compile(r'[\u4e00-\u9fff]')
_DUP_RE = re.compile(r'([\u4e00-\u9fff])\1')

# ── 十三辙参考表（高频尾字，非全量；用于把末字归类到辙）──────────────
RHYME_TABLE = {
    '发花': 'a ia ua', '梭波': 'o e uo', '乜斜': 'ie ue', '一七': 'i u er',
    '姑苏': 'u', '怀来': 'ai uai', '灰堆': 'ei ui', '遥条': 'ao iao',
    '由求': 'ou iu', '言前': 'an ian uan uan', '人辰': 'en in un un',
    '江阳': 'ang iang uang', '中东': 'eng ing ong iong',
}
RHYME_CHARS = {
    '发花': '花家下话大他她怕沙茶马画挂夸拿哪那查加价假夏霞牙雅华瓦把八爸打塔拉辣罢差',
    '梭波': '我多过说火歌河和个可课乐热色车扯舌折这者得德特波破婆磨佛坐错所锁落活货窝左做作',
    '乜斜': '别写些也夜叶姐解节借切且谢斜雪学月越约缺却确绝决',
    '一七': '你里的事是时日子一二地气机几已意记起知只纸志制吃持迟诗词次思四死衣以比笔雨鱼女句去西',
    '姑苏': '不无五苦哭古故路露树书数土度独读如入除出主住竹湖护呼铺服福母木目',
    '怀来': '来开爱白百买卖快怪怀坏外在才海还害太台赛盖彩菜排牌带待改该抬',
    '灰堆': '飞灰回会岁谁水追最醉对堆队给累雷类美妹每背被北黑尾伟为位味归贵鬼',
    '遥条': '到道高好老小笑要照找报抱跑毛猫早草少烧桥巧掉叫教交角脚药咬腰摇遥飘票苗庙条跳',
    '由求': '有又友手走头口后够斗楼漏酒就九久球秋求六留流柳牛油游收受愁臭休秀修丢',
    '言前': '山天年见面边点全远愿难南看干感间千前先言烟园晚万完断乱团暖船传穿川汉还安半满慢散三蓝脸',
    '人辰': '人心真深身神们门分云运军群春存村寸孙本奔根跟很恨恩因音金进尽信新林临',
    '江阳': '上长唱场光黄王往忘望方放房想香乡向江将讲样阳亮量两娘床装庄壮窗双霜帮忙当党汤堂糖浪',
    '中东': '风生声成城情清请听停行星名明命定东红中终同痛送梦冷疼能灯等更争正冰兵平瓶轻青穷雄',
}
CHAR2RHYME = {}
for _r, _cs in RHYME_CHARS.items():
    for _c in _cs:
        CHAR2RHYME.setdefault(_c, _r)

# ── 齿音高频字（z c s zh ch sh j q x 声母的常用字，非全量）────────────
SIBILANT = set('知只纸志制吃持迟诗时是事世势说水山生长常出声生前千亲请清青去前西四思死字自子走在'
               '做作最醉早草少烧手受吹春成城心新想小笑行些写谢雪相想向先现线选息习席洗细七起气期'
               '计算算三散岁碎缩所色塞思虽然让认日')

# ── AI 味大词黑名单（与附录 A 一致）────────────────────────────────
AI_WORDS = ['岁月', '时光', '流年', '青春', '红尘', '天涯', '沧桑', '远方', '梦想', '初心',
            '心灵', '灵魂', '喧嚣', '静好', '温柔以待', '人间值得', '迷失', '彷徨', '迷茫',
            '永不放弃', '勇敢飞翔', '照亮前方', '心中那份', '最深的眷恋']

# 句尾偏内敛的辙（副歌/爆发段落结尾最好避开）
CLOSED_RHYMES = {'一七', '姑苏', '灰堆', '由求'}
_LOW = ('副歌', '爆发', '高潮', '钩子', 'chorus')


def parse(path: str):
    raw = io.open(path, encoding='utf-8-sig', errors='replace').read()
    segs = []
    tag, buf = '', []

    def flush():
        if buf:
            segs.append((tag or '', [x for x in buf if x.strip()]))

    for line in raw.split('\n'):
        line = line.rstrip()
        if not line.strip():
            flush()
            buf = []
            continue
        m = _TAG_RE.match(line)
        if m:
            flush()
            buf = []
            tag = m.group(1).strip()
            if m.group(2).strip():
                buf.append(m.group(2).strip())
        else:
            buf.append(line)
    flush()
    return segs


def cjk(s):
    return _CJK_RE.findall(s)


def rhyme_of(ch):
    return CHAR2RHYME.get(ch, '?')


def analyze(segs):
    issues = []
    rows = []
    total = 0
    ai_hits = []
    sib_hits = []

    for i, (tag, lines) in enumerate(segs, 1):
        total += sum(len(cjk(x)) for x in lines)
        tails, rhymes = [], []
        for ln in lines:
            chs = cjk(ln)
            if not chs:
                continue
            t = chs[-1]
            tails.append(t)
            rhymes.append(rhyme_of(t))
        known = [r for r in rhymes if r != '?']
        main = max(set(known), key=known.count) if known else '?'
        rows.append({'no': i, 'tag': tag or '第 %d 段' % i, 'lines': len(lines),
                     'tails': ''.join(tails), 'rhymes': rhymes, 'main': main,
                     'chars': [len(cjk(x)) for x in lines]})

        # ① 辙口散
        if len(set(known)) >= 3:
            issues.append(('中', '%s：辙口散成 %d 个' % (rows[-1]['tag'], len(set(known))),
                           '末字：%s' % ''.join(tails),
                           '一段里换辙超过两次，唱起来像拼接。定一个主辙，把例外那句改掉。'))
        elif '?' in rhymes:
            issues.append(('低', '%s：有末字未能归辙' % rows[-1]['tag'],
                           '未能判定的末字：%s' % ''.join(t for t, r in zip(tails, rhymes) if r == '?'),
                           '参考表未收录，不一定是错 —— 耳朵听一遍，确认它跟主辙（%s）合不合。' % main))

        # ② 句尾闭口音（副歌/爆发段）
        if any(k in tag or k in tag.lower() for k in _LOW) and tails:
            closed = [t for t, r in zip(tails, rhymes) if r in CLOSED_RHYMES]
            if len(closed) >= 2:
                issues.append(('中', '%s：句尾连用闭口音' % rows[-1]['tag'],
                               '闭口收尾的字：%s' % ''.join(closed),
                               '闭口音收尾憋气、传不远。副歌句尾尽量落到开口音或鼻音上（江阳 / 言前 / 中东）。'))

        # ③ 齿音密度
        for j, ln in enumerate(lines, 1):
            sb = [c for c in cjk(ln) if c in SIBILANT]
            if len(sb) > 2:
                sib_hits.append('%s 第 %d 句：%s' % (rows[-1]['tag'], j, ''.join(sb)))
                issues.append(('中', '%s 第 %d 句齿音密集' % (rows[-1]['tag'], j),
                               '「%s」含齿音字 %d 个：%s' % (ln[:16], len(sb), ''.join(sb)),
                               '喷麦、刺耳。一句里齿音字压到 2 个以内，换掉其中一个。'))

        # ④ 字数异类句
        lens = [len(cjk(x)) for x in lines]
        for j in range(len(lens) - 1):
            if abs(lens[j] - lens[j + 1]) > 4:
                issues.append(('中', '%s 第 %d-%d 句字数打架' % (rows[-1]['tag'], j + 1, j + 2),
                               '%d 字 ⟷ %d 字，相差 %d' % (lens[j], lens[j + 1], abs(lens[j] - lens[j + 1])),
                               '同段内允许 ±2 字浮动。差超 4 字，作曲时必然要删字或加字。'))

        # ⑤ 叠字
        for j, ln in enumerate(lines, 1):
            for m in _DUP_RE.finditer(ln):
                issues.append(('低', '%s 第 %d 句有叠字' % (rows[-1]['tag'], j),
                               '「%s」' % m.group(0),
                               '叠字要单独成行，否则 AI 唱歌会吞字（「轻轻」「慢慢」连读就糊）。'))

        # ⑥ 生僻字
        for j, ln in enumerate(lines, 1):
            rare = []
            for ch in cjk(ln):
                try:
                    ch.encode('gb2312')
                except Exception:  # noqa: BLE001
                    rare.append(ch)
            if rare:
                issues.append(('中', '%s 第 %d 句有生僻字' % (rows[-1]['tag'], j),
                               '「%s」' % ''.join(rare),
                               'AI 咬字会崩 + 字幕难做 + 观众认不出。换常用同义字。'))

        # ⑦ AI 味大词
        for j, ln in enumerate(lines, 1):
            for w in AI_WORDS:
                if w in ln:
                    ai_hits.append(w)
                    issues.append(('中', '%s 第 %d 句命中大词' % (rows[-1]['tag'], j),
                                   '「%s」' % w,
                                   '这类词不能连着用 —— 成串出现，整首词就变成背景音。一首里不超过 2 个。'))

    # ⑧ 总量与副歌长度
    if total > 250:
        issues.append(('高', '全篇总字数偏多',
                       '共 %d 字（参考区间 120~200）' % total,
                       '作曲环节会被迫砍你的词 —— 那是在最不该动结构的时候动结构。先自己砍。'))
    elif total < 100:
        issues.append(('低', '全篇总字数偏少',
                       '共 %d 字（参考区间 120~200）' % total,
                       '约三分钟的歌填不满。看看是不是少了一段，或句子太短。'))

    for r in rows:
        if any(k in r['tag'] or k in r['tag'].lower() for k in _LOW):
            long_s = [(i + 1, n) for i, n in enumerate(r['chars']) if n > 10]
            for j, n in long_s:
                issues.append(('中', '%s 第 %d 句超过 10 字' % (r['tag'], j), '%d 字' % n,
                               '副歌是给嗓子发力的地方，不是给字数的地方。压到 10 字以内。'))

    if len(ai_hits) > 2:
        issues.append(('高', 'AI 味大词成串', '共命中 %d 个：%s' % (len(ai_hits), '、'.join(ai_hits)),
                       '超过 2 个就该动手删了 —— 这是「一眼机器味」最直接的来源。'))

    return rows, issues, total


def write_html(path, rows, issues, total):
    sev = {'高': '#E53935', '中': '#F57C00', '低': '#546E7A'}
    tr = ['<tr><td>%d</td><td>%s</td><td>%d</td><td class="tl">%s</td>'
          '<td><span class="main">%s</span></td></tr>'
          % (r['no'], html.escape(r['tag']), r['lines'], html.escape(r['tails']),
             html.escape(r['main'])) for r in rows]
    ii = ['<div class="iss"><span class="lv" style="background:%s">%s</span><b>%s</b>'
          '<p class="d">%s</p><p class="f">改法：%s</p></div>'
          % (sev.get(lv, '#546E7A'), lv, html.escape(t), html.escape(d), html.escape(f))
          for lv, t, d, f in issues]
    if not ii:
        ii.append('<div class="ok">✅ 可唱性体检全过。辙口稳、齿音净、无套话 —— 可以进 L5 交给批评方了。</div>')

    doc = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>可唱性体检报告</title>
<style>
:root{--bg:#0f1115;--card:#171a21;--fg:#e8eaf0;--dim:#9aa3b2;--line:#272c36;--acc:#43A047}
body.light{--bg:#f5f6f8;--card:#fff;--fg:#1a1d23;--dim:#5c6673;--line:#e3e6ea}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.65 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif;padding:28px}
.wrap{max-width:1020px;margin:0 auto}
h1{font-size:26px;margin:0 0 6px}
.sub{color:var(--dim);font-size:15px;margin-bottom:18px}
.bar{position:fixed;right:18px;top:18px;display:flex;gap:8px;z-index:9}
.bar button{background:var(--card);color:var(--fg);border:1px solid var(--line);border-radius:8px;padding:8px 13px;font-size:16px;cursor:pointer}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:20px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.card .k{color:var(--dim);font-size:14px}
.card .v{font-size:24px;font-weight:700;margin-top:4px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;font-size:15px}
th,td{padding:10px 12px;text-align:left;border-bottom:1px solid var(--line)}
th{background:color-mix(in srgb,var(--card) 70%,var(--fg) 6%);font-weight:600;font-size:14px;color:var(--dim)}
tbody tr:nth-child(even){background:color-mix(in srgb,var(--card) 92%,var(--fg) 4%)}
td.tl{font-size:18px;letter-spacing:3px}
.main{background:rgba(67,160,71,.18);border-radius:6px;padding:1px 8px}
.iss{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--acc);border-radius:10px;padding:12px 14px;margin:10px 0}
.iss .lv{display:inline-block;color:#fff;border-radius:6px;padding:1px 8px;font-size:13px;margin-right:8px}
.iss .d{margin:6px 0 2px;color:var(--dim);font-size:15px}
.iss .f{margin:2px 0 0;font-size:15px}
.ok{background:rgba(67,160,71,.12);border:1px solid var(--line);border-radius:10px;padding:14px 16px;font-size:16px}
.foot{color:var(--dim);font-size:14px;margin-top:22px}
</style></head><body><div class="wrap">
<div class="bar"><button onclick="fz(-1)">A－</button><button onclick="fz(1)">A＋</button>
<button onclick="document.body.classList.toggle('light')">切换底色</button></div>
<h1>可唱性体检报告</h1>
<div class="sub">词稿：__SRC__ ｜ 逐句末字归辙 + 听感三项 + AI 味筛查</div>
<div class="cards">
<div class="card"><div class="k">段数</div><div class="v">__NSEG__</div></div>
<div class="card"><div class="k">总字数</div><div class="v">__CHARS__</div></div>
<div class="card"><div class="k">问题条数</div><div class="v">__NISS__</div></div>
</div>
<table><thead><tr><th>段</th><th>标记</th><th>行数</th><th>末字辙口</th><th>本段主辙</th></tr></thead>
<tbody>
__ROWS__
</tbody></table>
<h2 style="font-size:20px;margin:26px 0 4px">体检清单</h2>
__ISSUES__
<div class="foot">十四辙参考表为**高频字表，非全量** —— 标「?」的字不是错，只是表里没有，请用耳朵确认。
末字那一列竖着看：**能一眼读出节奏的，就是押上了。**</div>
</div>
<script>
var base=16;
function fz(d){base=Math.max(12,Math.min(28,base+d*2));document.body.style.fontSize=base+'px';
document.querySelectorAll('td,th,.iss .f,.iss .d,td.tl,.sub,.foot').forEach(function(e){
e.style.fontSize=(base-1)+'px';});}
</script></body></html>"""
    doc = (doc.replace('__SRC__', html.escape(os.path.basename(path)))
              .replace('__NSEG__', str(len(rows)))
              .replace('__CHARS__', str(total))
              .replace('__NISS__', str(len(issues)))
              .replace('__ROWS__', '\n'.join(tr))
              .replace('__ISSUES__', '\n'.join(ii)))
    io.open(path, 'w', encoding='utf-8').write(doc)


def write_txt(path, rows, issues, total):
    order = {'高': 0, '中': 1, '低': 2}
    L = ['可唱性体检（sing_check %s）' % FILE_VERSION, '=' * 58,
         '段数 %d ｜ 总字数 %d ｜ 问题 %d 条' % (len(rows), total, len(issues)), '']
    for r in rows:
        L.append('第 %d 段 %s  主辙：%s   末字：%s' % (r['no'], r['tag'], r['main'], r['tails']))
    L.append('')
    if not issues:
        L.append('✅ 全部通过。')
    for i, (lv, t, d, f) in enumerate(sorted(issues, key=lambda x: order.get(x[0], 9)), 1):
        L.append('%2d. [%s] %s' % (i, lv, t))
        L.append('    %s' % d)
        L.append('    改法：%s' % f)
    L += ['', '-' * 58,
          '下一步：把本清单连同「送审包五件套」一起交给批评方（L5），',
          '     它就是一份现成的、可量化的约束条件。']
    io.open(path, 'w', encoding='utf-8').write('\n'.join(L))


def main() -> int:
    ap = argparse.ArgumentParser(description='词稿可唱性体检（lyric-master L3/L4）')
    ap.add_argument('src', help='词稿 txt')
    ap.add_argument('--out', default='', help='输出目录，默认与词稿同目录')
    a = ap.parse_args()

    if not os.path.exists(a.src):
        print('!! 找不到词稿：%s' % a.src)
        return 2
    out = a.out or os.path.dirname(os.path.abspath(a.src))
    os.makedirs(out, exist_ok=True)

    segs = parse(a.src)
    if not segs:
        print('!! 没解析出任何段落')
        return 2

    rows, issues, total = analyze(segs)
    hp = os.path.join(out, '可唱性体检报告.html')
    tp = os.path.join(out, '体检清单.txt')
    write_html(hp, rows, issues, total)
    write_txt(tp, rows, issues, total)

    print('段数 %d ｜ 总字数 %d ｜ 问题 %d 条' % (len(rows), total, len(issues)))
    print()
    for r in rows:
        print('  第 %d 段 %-8s 主辙 %-4s 末字 %s' % (r['no'], r['tag'][:8], r['main'], r['tails']))
    print()
    order = {'高': 0, '中': 1, '低': 2}
    for lv, t, d, _f in sorted(issues, key=lambda x: order.get(x[0], 9)):
        print('  [%s] %s —— %s' % (lv, t, d))
    print()
    print('→ %s' % hp)
    print('→ %s' % tp)
    return 0


if __name__ == '__main__':
    sys.exit(main())
