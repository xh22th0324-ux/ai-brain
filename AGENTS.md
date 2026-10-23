# AGENTS.md — 通用入口（任何 AI 先读这个）

本仓库是**跨模型的个人上下文包**，由三部分组成：

- `context/` — 我的想法、偏好、决策记录（让 AI 快速了解"我是谁、我怎么想事"）
- `skills/` — 可执行的方法论（让 AI 直接按既定流程干活，不用重新摸索）
- `tools/` — 拿来就能跑的独立小工具（不依赖仓库，给定输入产出结果）

设计目标：**换任何一个 AI（Claude / GPT / Gemini / 本地模型）接手，读 3 个文件就能开始产出**。

---

## 上手顺序（4 步，别跳）

**第 1 步是装技能，做完再往下读。**

### 1. 装 `graphify`（唯一必装）

这是本仓库里**唯一被我指定为「必装」的技能**，其余技能一律按需选装。

理由：接手陌生代码库时，最快的办法不是通读源码，而是先拿到它的**清单**（有哪些文件、多长、
每个文件有哪些函数/类、依赖哪些库）。`graphify` 一条命令给出这份清单，正好承接本仓库
「不要通读」的原则。

> ⚠️ **它不是调用图工具**。实测确认：`calls` 在分析阶段被提取，但汇总时被丢弃，
> 从不写进输出，也从不生成调用边。全库所有边都是 `type: "import"`，且 `to` 只是
> import 过来的**名字**（`from b import helper` → `to: "helper"`），不解析成本地文件，
> 无法区分「同目录的 b.py」和「pip 装的 b」。**要函数级调用链/架构图，换别的工具。**
它**零依赖**——纯 Python 标准库，不用 `pip`、不用 API key、不联网。

| 你的环境 | 怎么装 |
|---|---|
| 有技能目录的宿主（WorkBuddy 等） | 复制 `skills/graphify/` 到宿主技能目录，如 `~/.workbuddy/skills/graphify` |
| Claude Code / Codex CLI / Gemini CLI | 不用装，直接 `python3 skills/graphify/run.py …` |
| 只拿到单文件说明、没有仓库文件 | 向作者索取**整个目录**（39 KB，5 个文本文件，缺一个都跑不起来） |

```bash
python3 skills/graphify/run.py --selftest                            # 12 项全过才继续
python3 skills/graphify/run.py --command report --path <TARGET_DIR>  # 建立结构认知
```

四条实测提醒（不是推测，踩过）：

1. 只接受 `--command` / `--path` / `--output`，**位置参数必报错**。`SKILL.md` 开头的
   「实测用法」节已覆盖上游文档里那套不存在的 `graphify init/index` 命令
2. 真正的自检是 `run.py --selftest`；目录里的 `selftest.py` 自身有 bug，只报 `2/8 通过` 是假警报
3. **能分析什么、分析不到什么，差别很大**：`.py` 拿到函数名/类名/import 名列表；
   `.js/.ts/.go/.rs/.java` 正则近似，只有符号名与 import；`.jsx/.tsx/.c/.cpp` 只能数行数。
   **三者都没有调用关系**——别拿它给 C/C++ 出结构图，也别期待任何语言的调用链
4. **`--command mermaid` 是坏的，不要用**：单层目录下节点 id 会被写成 `(root)[(root)]`
   （Mermaid 不接受带括号的 id，渲染直接报语法错）；多子目录时则退化成「目录 → 第三方库」的
   噪音图，还会因空 import 产生 `scripts -->` 这种空节点。要图自己从 `scan` 的 JSON 画
5. **必须拿整个目录（5 个文件）**：`run.py` 只是 9 行转发壳，实现在 `scripts/main.py`。
   只下载 `run.py` 会报 `ModuleNotFoundError: No module named 'main'`

### 2. 读本文件（你在读）

### 3. 读 `context/PROFILE.md` — 我的背景与沟通偏好

### 4. 按任务查 `manifest.json` → 命中技能则读 `skills/<name>/SKILL.md`

**不要**通读整个仓库。按需检索，避免浪费上下文窗口。

---

## 任务路由

| 你要做的事 | 先看 |
|---|---|
| 接手陌生代码库、先摸清结构 | 先装 `graphify`（见上「第 1 步」） |
| 查我有什么技能可用 | `manifest.json` 的 `skills` 数组 |
| 做视频 / 歌词 / MV | `skills/lyric-master`、`skills/lyric-mv`、`skills/video-producer` |
| 做 PPT / Word / Excel | `skills/pptx`、`skills/zagens-office` |
| 图表与数据可视化 | `skills/smart-charts` |
| PS5 相关（游戏转换、部署、排障） | `skills/ps5` |
| Windows 主机调优、体检 | `skills/win-tune`、`skills/self-tune` |
| 了解我在某件事上的立场 / 过往决策 | `context/decisions/` |
| 了解我的表达风格偏好 | `context/PROFILE.md` |
| 要把目录下每个文件各自压成一个包 | `tools/zip_each.py`（见下方「随包工具」） |

---

## 技能调用约定

每个技能是一个目录，最小结构：

```
skills/<name>/
├── SKILL.md          # 必需：frontmatter(name, description) + 执行流程
├── references/       # 可选：深度资料，按需读，不要预设全读
└── scripts/          # 可选：可直接运行的脚本
```

执行规则：

1. **先读 `SKILL.md` 的 frontmatter**，`description` 命中当前任务才继续
2. **只读被 SKILL.md 显式引用的 reference**，不要遍历 `references/`
3. `scripts/` 里的脚本按其 docstring 调用，路径参数一律显式传入
4. 技能内的路径若出现 `<PLACEHOLDER>` 形式，说明已被脱敏，需向用户索取真实值

---

## 随包工具（`tools/`）

和 `skills/` 不同，这里**没有 SKILL.md，也不讲流程** —— 就是能直接跑的脚本。
`skills/` 回答"这件事该怎么做"，`tools/` 回答"这个动作有现成的，别重写"。

| 工具 | 作用 | 入口 |
|---|---|---|
| `zip_each` | 把目录下每个文件**各自**压成一个独立压缩包，原文件不动；已压过且源未变的自动跳过 | `tools/zip_each.py`（Windows 可双击 `tools/zip_each.bat`） |

调用规则：

1. **路径参数一律显式传入**，不要依赖"当前工作目录"——AI 的 cwd 常常不是用户以为的那个
2. 动手前先 `--dry-run` 或 `--check`，把计划念给用户听，确认了再真压
3. 这些脚本**只读源文件、只写新包**，不会删改原文件；涉及删除的操作不要用它
4. 每个工具的详细行为见 `tools/README.md`；`manifest.json` 的 `tools` 数组里有摘要与校验和
5. 需要「一个总包」而不是「每个文件一个包」时，别用它 —— 那是 `zip -r` /
   `scripts/make_zip.py` 的事

---

## 写作规范（往本仓库添加内容时）

笔记统一放在 `context/ideas/`（想法）或 `context/decisions/`（决策），必须带 frontmatter：

```yaml
---
title: 一句话标题
date: 2026-10-22
tags: [主题1, 主题2]
status: draft | settled
source: claude | gpt | 自己想的
---
```

正文要求：

- 一篇笔记只讲一件事（原子化），标题不超过 20 字
- 结论写最前面，理由写后面
- 涉及取舍时，必须写出**放弃了什么**，否则半年后看不懂
- 不写"我们讨论了很多"这类过程记录，只留结论与依据

---

## 隐私与安全（硬性规则）

1. **禁止提交**：密码、token、私钥、API key、真实内网 IP、真实姓名以外的个人信息
2. 敏感值一律用占位符：`<PASSWORD>`、`<PRIVATE_IP>`、`<USER_HOME>`、`<EMAIL>`
3. 需要凭据的脚本，从环境变量读取，不写默认值
4. 提交前必须通过 `python scripts/check_secrets.py`（CI 也会跑）

---

## 维护约定

| 动作 | 命令 |
|---|---|
| 导出/更新技能 | `python scripts/export_skills.py` |
| 重建清单 | `python scripts/build_manifest.py` |
| 密钥体检 | `python scripts/check_secrets.py` |
| 新增想法笔记 | 复制 `context/ideas/_template.md` |

技能有更新时，**先改本地真实技能目录，再跑 export**，不要直接手改 `skills/`（会被覆盖）。

新增工具时：直接往 `tools/` 放脚本（模块 docstring 第一行会作为摘要进清单），
同名的 `.bat/.cmd/.sh` 会被自动识别为启动器，然后跑一次 `build_manifest.py`。
**不需要**给它写 SKILL.md —— 那是技能的格式，工具不是技能。
