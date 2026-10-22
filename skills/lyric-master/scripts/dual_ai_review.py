# -*- coding: utf-8 -*-
"""
dual_ai_review.py — 双 AI 互批研讨引擎

一个写稿、一个挑错，自动往返 N 轮，每轮落盘，产出研讨纪要 + 定稿候选。
机制实录见 references/dual-ai-review-case.md（《我辈本是天上仙》4 轮实战）。

两种运行模式：
  auto   全自动 —— 需要两个 OpenAI 兼容接口的 API Key（DeepSeek / 火山方舟 /
         通义 / Kimi / 智谱 / 硅基流动 / 本地 Ollama 等，格式全兼容）
  manual 半自动 —— 不需要 Key。脚本只负责生成每一轮的提示词并落盘，
         你复制到任意两个网页版 AI 里粘贴，把回复存回指定文件即可。

零第三方依赖（只用标准库）。

作者：后山人　|　许可：随技能包分发
"""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

FILE_VERSION = "v1.0"
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent


# ═══════════════════════════════════════════════════════════════════
#  提示词 —— 从这里改，不用动代码
# ═══════════════════════════════════════════════════════════════════

CREATOR_SYSTEM = """你是一位职业词人，为一首中文歌曲创作歌词。

你的职责：
1. 按给定主题、情绪、目标受众写词，或按批评意见修订已有版本
2. 保持歌词的可唱性：押韵、音节顺口、副歌有记忆点
3. 有画面感：意象要具体、能拍出来，不用空泛大词

【你的反驳权 —— 这一点非常重要】
你不是无脑执行批评意见的机器。如果批评方的意见你认为不成立，你有权拒绝，
但必须给出理由。常见的三类可反驳情形：
  - 覆盖面偏差：批评方假设的场景与实际受众不符
  - 批评方自己用错了典故、事实、出处
  - 语体断裂：改法会把统一的语体切碎
拒绝时，格式为：
  【反驳】不采纳第 N 条。理由：……

【硬性约束】
- 已由真人确认过的结构、句序、核心意象，不得擅自推翻。
  确实需要大改时，必须先写明「需大改结构，理由：……」，等待真人裁定。
- 不写具体真人歌手名、不模仿特定在世歌手的作品
- 不使用「岁月/时光/梦想/远方」这类空泛大词作为抒情支点

【输出格式 —— 严格照此，不要加额外说明】
第 1 段：逐条回应（对每条批评：【采纳】改成了什么 / 【反驳】为什么）
第 2 段：以下是完整的修订版歌词（不要只给改动片段，要给全文）
"""

CRITIC_SYSTEM = """你是一位极其挑剔的歌曲制作总监，人称「毒舌批评家」。

【最重要的一条：不许夸】
不要写「整体不错」「很有意境」「建议继续保持」这类话。
你唯一的职责是找出问题。夸一句就是失职。

【批评必须落点可验证】
每一条批评都要写成三段式：
  原句：（引用原文那一句）
  问题：（必须落到可验证的层面——韵脚辙口、音节节奏、典故出处、
        开口音/闭口音、语体一致性、意象可拍性、事实性错误。
        禁止写「可以更有画面感」这种无落点的话）
  改法：（给出具体替换方案）

【批判清单 —— 逐条过一遍】
1. AI 味：指出具体的套话、空泛抒情、大词堆砌出现在哪一句
2. 意象可拍性：哪些句子拍不出来？具体列出
3. 副歌钩子：有没有一句能被记住？没有的话，缺在哪
4. 口吻统一：人称、性别视角、时代感有没有跳跃
5. 硬凑押韵：哪句是为了押韵牺牲了语义
6. 冗余：哪两句删掉完全不影响语义
7. 唱腔顺口度：连续同音、叠字、开口音闭口音排布是否拗口
8. 事实核查：典故、年代、人物关系逐一核对（你自己也要查证，别想当然）

【收敛规则】
- 如果还有结构性问题 → 列出来，最后一行写「建议再改一轮」
- 如果只剩措辞偏好，没有结构性问题 → 最后一行写「可定稿」
- 已经指出过的问题，对方若不采纳并给出理由，你只能再驳一次。
  第二次仍不采纳时，必须把该条标为「待真人终裁」，不得继续纠缠。

【输出格式 —— 严格照此】
先列批评条目（三段式），最后单独一行给出结论：建议再改一轮 / 可定稿
"""

CREATOR_OPENING = """请为下面这首歌写一版歌词初稿。

【主题】{theme}
【情绪基调】{mood}
【目标受众】{audience}
【篇幅要求】{length}
【已有素材 / 必须保留的元素】{material}

请直接输出歌词全文，分行清晰，标注 [主歌1] [副歌] [主歌2] [副歌] [桥段] [副歌] 等段落。
"""

CREATOR_REVISE = """上一版歌词如下：

────────────
{previous}
────────────

批评方的意见如下：

────────────
{critique}
────────────

请按你的输出格式要求处理：
第 1 段逐条回应（【采纳】或【反驳】+理由），第 2 段给出完整修订版歌词。

补充约束：这已是第 {round_no} 轮修改，真人已认可现有整体结构。
如需大改结构，必须先写明「需大改结构，理由：……」。
"""

def human_note(n):
    """把「已过 N 轮人工修改」写成人话（n=0 时别说「已过 0 轮」）。"""
    if not n:
        return "本稿为初稿，尚未经过人工修改，用户认可整体方向"
    return f"本稿已过 {n} 轮人工修改，用户认可现有结构"


CRITIC_FIRST = """以下是待审歌词：

────────────
{text}
────────────

这是一首用于 {theme} 主题、面向 {audience} 的中文歌。
请按你的批判清单和输出格式，逐条给出批判意见。

补充约束：{human_note}。
大改结构需给出压倒性理由。
"""

CRITIC_NEXT = """以下是创作方根据你上一轮意见给出的修订版：

────────────
{text}
────────────

创作方对你上一轮意见的回应：

────────────
{response}
────────────

请按你的批判清单和输出格式，逐条给出批判意见。
注意收敛规则：已指出过的问题若对方不采纳并给出理由，你只能再驳一次，
第二次仍不采纳则标为「待真人终裁」。
"""


# ═══════════════════════════════════════════════════════════════════
#  API 调用（OpenAI 兼容格式，一套代码通吃国内主流平台）
# ═══════════════════════════════════════════════════════════════════

def call_openai_compatible(conf, system_prompt, user_prompt, verbose=True):
    """调用任意 OpenAI 兼容接口。conf = {base_url, api_key, model, temperature}"""
    base = conf.get("base_url", "").rstrip("/")
    if not base:
        raise ValueError("base_url 为空")
    url = base + "/chat/completions"

    payload = {
        "model": conf.get("model", ""),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": conf.get("temperature", 0.8),
        "stream": False,
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + conf.get("api_key", ""),
        },
        method="POST",
    )

    # 绕过系统代理（本机若挂了回环代理会拦掉请求）
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    last_err = None
    for attempt in range(3):
        try:
            with opener.open(req, timeout=conf.get("timeout", 180)) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            text = data["choices"][0]["message"]["content"]
            if verbose:
                print(f"    [OK] {len(text)} 字")
            return text.strip()
        except Exception as e:
            last_err = e
            if verbose:
                print(f"    [重试 {attempt+1}/3] {type(e).__name__}: {e}")
            time.sleep(3)
    raise RuntimeError(f"接口调用失败：{last_err}")


def provider_preset(name):
    """常见平台的预设 base_url，用户只需填 key。"""
    presets = {
        "deepseek":  ("https://api.deepseek.com/v1",            "deepseek-chat"),
        "doubao":    ("https://ark.cn-beijing.volces.com/api/v3", "doubao-pro-32k"),
        "qwen":      ("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"),
        "kimi":      ("https://api.moonshot.cn/v1",              "moonshot-v1-8k"),
        "zhipu":     ("https://open.bigmodel.cn/api/paas/v4",    "glm-4"),
        "silicon":   ("https://api.siliconflow.cn/v1",           "deepseek-ai/DeepSeek-V3"),
        "ollama":    ("http://127.0.0.1:11434/v1",               "qwen2.5:14b"),
        "lmstudio":  ("http://127.0.0.1:1234/v1",                "local-model"),
        "custom":    ("", ""),
    }
    return presets.get(name, ("", ""))


# ═══════════════════════════════════════════════════════════════════
#  工具
# ═══════════════════════════════════════════════════════════════════

def log(msg):
    print(msg, flush=True)


def hr(title=""):
    line = "─" * 60
    print(f"\n{line}")
    if title:
        print(f"  {title}")
        print(line)


def save(path, content):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(content, encoding="utf-8")


def is_final(critique_text):
    """判断批评方是否给出「可定稿」。取最后一次出现的结论行。"""
    tail = critique_text[-400:]
    if "可定稿" in tail:
        return True
    if "建议再改一轮" in tail:
        return False
    # 兜底：全文找
    return "可定稿" in critique_text and "建议再改一轮" not in critique_text


def split_creator_output(text):
    """把创作方输出拆成 (回应段, 歌词段)。拆不开就整段当歌词。"""
    m = re.search(r"修订版歌词|以下是完整的修订版|完整修订版", text)
    if m:
        return text[:m.start()].strip(), text[m.start():].strip()
    m2 = re.search(r"^\s*\[?(主歌|副歌|桥段|前奏|间奏|尾奏)", text, re.M)
    if m2:
        return text[:m2.start()].strip(), text[m2.start():].strip()
    return "", text.strip()


# ═══════════════════════════════════════════════════════════════════
#  主流程
# ═══════════════════════════════════════════════════════════════════

def run_auto(cfg, outdir):
    creator = cfg["creator"]
    critic = cfg["critic"]
    task = cfg["task"]
    max_rounds = cfg.get("max_rounds", 3)

    log(f"  创作方：{creator.get('model')} @ {creator.get('base_url')}")
    log(f"  批评方：{critic.get('model')} @ {critic.get('base_url')}")
    log(f"  最大轮次：{max_rounds}")

    # ── 第 0 步：出初稿 ──
    hr("第 0 步 · 创作方出初稿")
    opening = CREATOR_OPENING.format(**task)
    draft = call_openai_compatible(creator, CREATOR_SYSTEM, opening)
    save(outdir / "00_初稿_创作方.md", draft)
    log(f"  已存：00_初稿_创作方.md")

    history = []
    final_ok = False

    # ── 第 1 步：批评方首审 ──
    hr("第 1 步 · 批评方首审")
    c1 = call_openai_compatible(
        critic, CRITIC_SYSTEM,
        CRITIC_FIRST.format(text=draft, theme=task["theme"],
                            audience=task["audience"],
                            human_note=human_note(cfg.get("human_rounds", 0))),
    )
    save(outdir / "01_批评方_首审.md", c1)
    history.append(("初稿", draft, c1))
    log(f"  已存：01_批评方_首审.md")

    for r in range(1, max_rounds + 1):
        # 检查上一条批评是否已判定可定稿
        if is_final(c1 if r == 1 else cprev):
            log(f"  批评方已判定「可定稿」，提前结束")
            final_ok = True
            break

        hr(f"第 {r+1} 步 · 创作方回应 + 修订（第 {r} 轮）")
        if r == 1:
            revise_prompt = CREATOR_REVISE.format(
                previous=draft, critique=c1, round_no=r)
            prev_crit = c1
        else:
            revise_prompt = CREATOR_REVISE.format(
                previous=current, critique=prev_crit, round_no=r)

        raw = call_openai_compatible(creator, CREATOR_SYSTEM, revise_prompt)
        response, current = split_creator_output(raw)
        save(outdir / f"{r+1:02d}_创作方_第{r}轮修订.md", raw)

        hr(f"第 {r+2} 步 · 批评方复审（第 {r} 轮）")
        prev_crit = call_openai_compatible(
            critic, CRITIC_SYSTEM,
            CRITIC_NEXT.format(text=current, response=response or "（未单独给出回应段）"),
        )
        save(outdir / f"{r+2:02d}_批评方_第{r}轮复审.md", prev_crit)
        history.append((f"第 {r} 轮", current, prev_crit))

        if is_final(prev_crit):
            log(f"  批评方输出「可定稿」")
            final_ok = True
            break
        if r == max_rounds:
            break

    return history, current, final_ok


def run_manual(cfg, outdir):
    """半自动：把每轮提示词落盘，用户自己粘贴到网页 AI。"""
    task = cfg["task"]
    max_rounds = cfg.get("max_rounds", 3)

    log("  半自动模式 —— 不调用接口，只生成提示词文件")
    log(f"  输出目录：{outdir}")

    guide = []
    guide.append("# 双 AI 互批研讨 · 手工操作指引（半自动）\n")
    guide.append(f"生成时间：{datetime.now():%Y-%m-%d %H:%M}\n")
    guide.append("## 准备\n")
    guide.append("打开两个不同平台的 AI 网页（例：豆包 + DeepSeek）。\n")
    guide.append("一个当**创作方**，一个当**批评方**，之后全程不要换角色。\n")

    guide.append("\n## 第 0 步 · 创作方提示词\n\n```")
    guide.append(CREATOR_SYSTEM)
    guide.append("```\n")

    guide.append("## 每轮的批评方提示词（粘贴一次，长期有效）\n\n```")
    guide.append(CRITIC_SYSTEM)
    guide.append("```\n")

    guide.append("## 第 0 步 · 给创作方的开工指令\n\n```")
    guide.append(CREATOR_OPENING.format(**task))
    guide.append("```\n")

    guide.append("---\n## 循环（跑 2~3 轮）\n")
    for r in range(1, max_rounds + 1):
        guide.append(f"### 第 {r} 轮")
        guide.append(f"1. 把创作方的稿子全文，连同下面的指令，发给**批评方**：")
        guide.append("\n```")
        if r == 1:
            guide.append(CRITIC_FIRST.format(
                text="【此处粘贴创作方歌词全文】",
                theme=task["theme"], audience=task["audience"],
                human_note=human_note(cfg.get("human_rounds", 0))))
        else:
            guide.append(CRITIC_NEXT.format(
                text="【此处粘贴创作方最新歌词全文】",
                response="【此处粘贴创作方上一轮的逐条回应】"))
        guide.append("```\n")
        guide.append(f"2. 把批评方的意见全文，连同下面的指令，发给**创作方**：")
        guide.append("\n```")
        guide.append(CREATOR_REVISE.format(
            previous="【此处粘贴上一版歌词】",
            critique="【此处粘贴批评意见】",
            round_no=r))
        guide.append("```\n")
        guide.append("3. 若批评方最后一行是**「可定稿」**，循环结束。\n")

    guide.append("---\n## 收尾 · 交真人终裁\n")
    guide.append("把定稿候选 + 全部批评意见，逐条过一遍：")
    guide.append("采纳哪些、保留哪些、理由是什么，写进 `终裁记录.md`。")
    guide.append("这份记录与每一轮稿件一起，构成创作过程证据链。\n")

    save(outdir / "研讨指引.md", "\n".join(guide))
    log(f"  已存：研讨指引.md")
    return None, None, None


def write_minutes(outdir, cfg, history, final_lyric, final_ok):
    lines = []
    lines.append("# 双 AI 互批研讨 · 纪要\n")
    lines.append(f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M}")
    lines.append(f"- 引擎版本：{FILE_VERSION}")
    lines.append(f"- 主题：{cfg['task']['theme']}")
    lines.append(f"- 目标受众：{cfg['task']['audience']}")
    lines.append(f"- 收敛状态：{'✅ 批评方判定可定稿' if final_ok else '⚠️ 达到轮次上限，仍有分歧'}")
    lines.append(f"- 评审轮数：{len(history)} 轮（含首审）")

    for name, text, crit in history:
        lines.append(f"\n---\n\n## {name}\n")
        lines.append("### 稿\n\n```\n" + text + "\n```\n")
        lines.append("### 批评\n\n```\n" + crit + "\n```\n")

    if final_lyric:
        lines.append("\n---\n\n## 定稿候选\n\n```\n" + final_lyric + "\n```\n")
    lines.append("\n---\n\n## 真人终裁记录（待填）\n")
    lines.append("| 批评条目 | 采纳 / 保留 | 理由 |")
    lines.append("|---|---|---|")
    lines.append("|  |  |  |\n")
    lines.append("> 全部条目裁定完毕、真人签字确认后，本歌词方可进入作曲环节。\n")

    save(outdir / "研讨纪要.md", "\n".join(lines))
    log(f"  已存：研讨纪要.md")


def main():
    hr(f"双 AI 互批研讨引擎 {FILE_VERSION}")
    print(f"  作者：后山人　|　机制实录见 references/dual-ai-review-case.md")

    # ── 读配置 ──
    cfg_path = SCRIPT_DIR / "config.json"
    if not cfg_path.exists():
        log(f"\n[错误] 找不到配置文件：{cfg_path}")
        log("       请把 config.example.json 复制一份改名为 config.json 再填内容。")
        return 1

    # 用 utf-8-sig：兼容记事本存出来的带 BOM 文件（这是 Windows 上最常见的报错源）
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as e:
        log(f"\n[错误] config.json 格式不对：{e}")
        log("       常见原因：多写了逗号、少了引号、中文引号写成了英文引号。")
        log("       建议用 https://jsonlint.com 校验一下。")
        return 1

    # ── 输出目录 ──
    outdir = Path(cfg.get("output_dir", str(SKILL_DIR / "out")))
    if not outdir.is_absolute():
        outdir = SKILL_DIR / outdir
    stamp = datetime.now().strftime("%m%d_%H%M%S")
    base = outdir / f"{cfg['task'].get('title', 'untitled')}_{stamp}"
    outdir = base
    n = 2
    while outdir.exists():      # 防止同秒重名互相覆盖
        outdir = Path(f"{base}_{n}")
        n += 1
    outdir.mkdir(parents=True, exist_ok=True)
    log(f"\n  输出目录：{outdir}")

    mode = cfg.get("mode", "auto").lower()
    log(f"  运行模式：{mode}")

    if mode == "manual":
        run_manual(cfg, outdir)
        hr("完成")
        log(f"  照 {outdir / '研讨指引.md'} 走一遍即可。")
        return 0

    # auto 模式：检查 key
    missing = []
    for role in ("creator", "critic"):
        c = cfg.get(role, {})
        if not c.get("api_key") or c.get("api_key", "").startswith("sk-填"):
            missing.append(role)
    if missing:
        log(f"\n[提示] {'、'.join(missing)} 没填 API Key。")
        log("       已自动切换到半自动模式（生成提示词，你手工粘贴）。")
        log("       想全自动：把 config.json 里的 mode 改成 auto，并填好两边的 key。\n")
        run_manual(cfg, outdir)
        hr("完成（半自动）")
        log(f"  照 {outdir / '研讨指引.md'} 走一遍即可。")
        return 0

    history, final_lyric, final_ok = run_auto(cfg, outdir)
    write_minutes(outdir, cfg, history, final_lyric, final_ok)

    hr("完成")
    log(f"  收敛状态：{'✅ 可定稿' if final_ok else '⚠️ 达上限仍有分歧'}")
    log(f"  定稿候选：{outdir / '研讨纪要.md'}")
    log(f"\n  ⚠️ 最后一步必须由真人做：逐条裁定，填进「真人终裁记录」。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n  已中断。已生成的文件都在输出目录里，可续跑。")
        sys.exit(130)
    except Exception as e:
        print(f"\n[异常] {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
