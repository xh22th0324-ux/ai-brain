# -*- coding: utf-8 -*-
"""把上下文包压成「单文件版」，用于直接粘贴进对话。

用途：有些 AI 拿不到上传的文件（跨机器、沙箱无共享目录、上传失败），
此时把本文件全文粘进对话即可，不依赖任何文件传输链路。

生成物 HANDOFF-SINGLE.md 是派生物，不要手改 —— 改源文件后重跑本脚本。

用法:
    python scripts/make_single.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_manifest import read_frontmatter  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "HANDOFF-SINGLE.md"

DESC_LIMIT = 130


def strip_frontmatter(text: str) -> str:
    """去掉 YAML frontmatter（它是给仓库工具看的，粘贴时是噪音）。"""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2].lstrip("\n")
    return text


def drop_private_notice(text: str) -> str:
    """去掉「本文件会随仓库公开」这类只对维护者有用的提示。"""
    return re.sub(r"^>\s*⚠️.*?(?=\n\n|\Z)", "", text, flags=re.M | re.S).lstrip()


def load_skills() -> list[tuple[str, str]]:
    """技能名 + 描述。优先中文描述，其次英文，最后回退 manifest 里存的。"""
    mf = REPO / "manifest.json"
    if not mf.is_file():
        print("! manifest.json 不存在，先运行 build_manifest.py", file=sys.stderr)
        return []
    data = json.loads(mf.read_text(encoding="utf-8"))
    out = []
    for s in data.get("skills", []):
        name = s.get("name") or s.get("dir", "?")
        desc = ""
        md = REPO / "skills" / s.get("dir", "") / "SKILL.md"
        if md.is_file():
            meta = read_frontmatter(md)
            for key in ("description_zh", "description", "description_en"):
                val = meta.get(key)
                if isinstance(val, str) and val.strip():
                    desc = val.strip()
                    break
        if not desc:
            desc = s.get("description") or ""
        desc = re.sub(r"\s+", " ", desc).strip()
        if len(desc) > DESC_LIMIT:
            desc = desc[:DESC_LIMIT].rstrip() + "…"
        out.append((name, desc))
    return out


def load_tools() -> list[tuple[str, str]]:
    """工具名 + 摘要，取自 manifest.json 的 tools 数组（由 build_manifest 生成）。"""
    mf = REPO / "manifest.json"
    if not mf.is_file():
        return []
    try:
        data = json.loads(mf.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    out = []
    for t in data.get("tools", []):
        name = t.get("name") or "?"
        desc = re.sub(r"\s+", " ", t.get("summary") or "").strip()
        out.append((name, desc))
    return out


def main() -> int:
    start_here = (REPO / "00-START-HERE.md").read_text(encoding="utf-8")
    profile = strip_frontmatter((REPO / "context" / "PROFILE.md").read_text(encoding="utf-8"))
    agents = strip_frontmatter((REPO / "AGENTS.md").read_text(encoding="utf-8"))
    skills = load_skills()
    tools = load_tools()

    # AGENTS.md 里只摘「尖括号」说明出自 00-START-HERE；AGENTS 本身不进单文件版
    def section(text: str, title: str) -> str:
        m = re.search(rf"^##\s*{re.escape(title)}\s*$(.*?)(?=^##\s|\Z)", text, re.M | re.S)
        return m.group(1).strip() if m else ""

    lines: list[str] = []
    A = lines.append

    A("<!-- 由 scripts/make_single.py 生成，不要手改 -->")
    A("")
    A("# 个人上下文包 · 单文件版")
    A("")
    A("> **给 AI 的读法**：这是一份工作说明书，不是要你总结的资料。")
    A("> 读完直接按下面「沟通偏好」行事，**不要输出摘要或能力清单**。")
    A("> 你手上只有这一份文件，看不到原始仓库；需要更细的流程时向我要。")
    A("")
    A("---")
    A("")

    # 1) 档案（最重要，放最前）
    prof = drop_private_notice(profile)
    prof = re.sub(r"^## ", "### ", prof, flags=re.M)   # 先降级正文小节
    prof = re.sub(r"^#\s*我的档案\s*$", "## 我是谁", prof, flags=re.M)  # 再替换大标题
    A(prof.strip())
    A("")
    A("---")
    A("")

    # 1.5) 唯一必装技能
    # 技能表把十几项平铺在一起，读者看不出哪个是必装 —— 必须单独点出来，
    # 并明说「文件不在你手上」，否则它会去找不存在的 skills/graphify 路径。
    A("## 先装这个（唯一必装）")
    A("")
    A("`graphify` 是我指定的**唯一必装技能**，其余技能按需选装。作用：一条命令给出一个")
    A("代码库的结构（文件 / 函数 / 调用边），省掉通读源码。**零依赖**——纯 Python 标准库，")
    A("不用 pip、不用 API key、不联网。")
    A("")
    A("文件不在你手上，需要时向我要 `skills/graphify/`（39 KB，5 个文本文件）。")
    A("拿到后先自检，12 项全过才继续：")
    A("")
    A("```bash")
    A("python3 skills/graphify/run.py --selftest                             # 12 项全过才继续")
    A("python3 skills/graphify/run.py --command report --path <TARGET_DIR>")
    A("```")
    A("")
    A("只接受 `--command` / `--path` / `--output`，位置参数会报错；")
    A("只有 `.py` 是完整分析（含调用边），`.jsx/.tsx/.c/.cpp` 只能数行数。")
    A("")
    A("---")
    A("")

    # 2) 技能清单
    A(f"## 我有什么能力（{len(skills)} 个技能）")
    A("")
    A("| 技能 | 用途 |")
    A("|---|---|")
    for name, desc in skills:
        A(f"| `{name}` | {desc} |")
    A("")
    A("---")
    A("")

    # 2.5) 随包小工具
    # 单文件版的读者手上没有仓库，所以必须说清"文件不在你手上"，
    # 否则它会去 `tools/` 找不存在的路径 —— 这正是 00-START-HERE 全文不能搬进来的原因。
    if tools:
        A("## 随包小工具（文件不在你手上）")
        A("")
        A("除了技能，仓库里还有能直接跑的独立脚本。**现在不在你手上**：需要时向我要；")
        A("拿不到就按下面的描述实现，其中「原文件不动」和「已压过就跳过」是硬要求。")
        A("")
        A("| 工具 | 作用 |")
        A("|---|---|")
        for name, desc in tools:
            A(f"| `{name}` | {desc} |")
        A("")
        A("---")
        A("")

    # 3) 占位符分类
    # 只摘这一节。不能把 00-START-HERE 全文搬进来 —— 它讲的是「去读另外两个文件」，
    # 而那两个文件的内容已经在本文件里了，搬进来会让对方去找不存在的路径。
    # 同理，AGENTS.md 的「技能调用约定」「隐私与安全」也不搬：那是给维护者看的
    # （怎么提交、怎么跑 check_secrets），对单文件版的读者只是噪音，还会误导它去找脚本。
    ph = section(start_here, "尖括号有两种，别搞混")
    if ph:
        A("## 尖括号有两种，别搞混")
        A("")
        A(ph)
        A("")
        A("---")
        A("")

    # 4) 读完先对齐，别急着产出 —— 这是整份文件最重要的指令
    A("## 读完先别产出")
    A("")
    A("用三条回答我，然后就停：")
    A("")
    A("1. 你判断我是什么样的人、希望被怎么回应（三句，别展开）")
    A("2. 你现在手上有哪些能直接用的能力（只列技能名，不解释）")
    A("3. 要开始干活，你还缺哪些信息（**最多 3 项**，按阻塞程度排序，")
    A("   不要写「请提供更多背景」这种泛项）")
    A("")
    A("技能的具体执行流程不在这份文件里 —— 命中哪个技能直接告诉我，我把它发给你。")

    text = "\n".join(lines).rstrip() + "\n"
    # 显式写 LF：Path.write_text 默认会把 \n 转成 os.linesep，
    # 那样 Windows 生成 CRLF、Linux 生成 LF，CI 的 git diff 必然误报
    # （manifest.json 早先就踩过这个坑）。
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"已生成: {OUT}")
    print(f"字符数: {len(text)}   技能: {len(skills)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
