# AGENTS.md — 通用入口（任何 AI 先读这个）

本仓库是**跨模型的个人上下文包**，由两部分组成：

- `context/` — 我的想法、偏好、决策记录（让 AI 快速了解"我是谁、我怎么想事"）
- `skills/` — 可执行的方法论（让 AI 直接按既定流程干活，不用重新摸索）

设计目标：**换任何一个 AI（Claude / GPT / Gemini / 本地模型）接手，读 3 个文件就能开始产出**。

---

## 上手顺序（3 步，别跳）

1. 读本文件（你在读）
2. 读 `context/PROFILE.md` — 我的背景与沟通偏好
3. 按任务查 `manifest.json` → 命中技能则读 `skills/<name>/SKILL.md`

**不要**通读整个仓库。按需检索，避免浪费上下文窗口。

---

## 任务路由

| 你要做的事 | 先看 |
|---|---|
| 查我有什么技能可用 | `manifest.json` 的 `skills` 数组 |
| 做视频 / 歌词 / MV | `skills/lyric-master`、`skills/lyric-mv`、`skills/video-producer` |
| 做 PPT / Word / Excel | `skills/pptx`、`skills/zagens-office` |
| 图表与数据可视化 | `skills/smart-charts` |
| PS5 相关（游戏转换、部署、排障） | `skills/ps5` |
| Windows 主机调优、体检 | `skills/win-tune`、`skills/self-tune` |
| 了解我在某件事上的立场 / 过往决策 | `context/decisions/` |
| 了解我的表达风格偏好 | `context/PROFILE.md` |

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
