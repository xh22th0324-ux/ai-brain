# ai-brain

把「和 AI 聊出来的想法」和「已经跑通的技能」固化成一个**与模型无关的上下文包**。
换一个 AI、换一台机器，读几个文件就能接着干活，不用重头解释。

## 它解决什么问题

| 常见痛点 | 本仓库的做法 |
|---|---|
| 每次换 AI 都要重新交代背景 | `context/PROFILE.md` 一份档案，谁读都懂 |
| 好想法聊完就散落在对话里 | `context/ideas/` 原子笔记，带标签可检索 |
| 技能绑在某一个工具里 | `skills/` 统一成 `SKILL.md` + 脚本，任何 AI 可读 |
| 决策半年后想不起为什么 | `context/decisions/` 强制记录取舍 |

## 快速开始

```bash
git clone <your-repo-url>
cd ai-brain
python scripts/build_manifest.py      # 生成清单
python scripts/check_secrets.py       # 密钥体检
```

然后让任意 AI 从 `AGENTS.md` 开始读。

### 唯一必装技能：`graphify`

[`skills/graphify`](skills/graphify/SKILL.md) 是**指定必装**的一项，其余技能按需选装。
代码知识图谱，零依赖（纯标准库）、不联网、不需要 API key。
交给别的 AI 时，要求它先装这个再干别的：

```bash
python3 skills/graphify/run.py --selftest    # 12 项全过才继续
python3 skills/graphify/run.py --command report --path <目标目录>
```

**换 AI 时该怎么开口，见 [`HOW-TO-HANDOFF.md`](HOW-TO-HANDOFF.md)** ——
里面是可直接复制粘贴的话术，以及为什么会话术比文件更重要。

**对方读不到文件时，用 [`HANDOFF-SINGLE.md`](HANDOFF-SINGLE.md)** ——
整包压成的一页纸（约 3300 字符），直接粘进对话即可。
实测最高频的失败不是"话说不清"，而是"文件根本没送到"。

## 目录

```
ai-brain/
├── 00-START-HERE.md     # 给「收到压缩包那一方」看的入口卡
├── HANDOFF-SINGLE.md    # 单文件版（生成物）：粘进对话即可，不依赖上传
├── AGENTS.md            # 通用入口，任何 AI 从这里开始
├── HOW-TO-HANDOFF.md    # 给「我」看的：投递路线 + 开口话术
├── manifest.json        # 机器可读索引（技能 + 笔记）
├── context/
│   ├── PROFILE.md       # 我的背景、偏好、沟通风格
│   ├── ideas/           # 想法笔记（原子化）
│   └── decisions/       # 决策记录（含放弃项）
├── skills/              # 技能包，每个含 SKILL.md（graphify 为唯一必装）
├── tools/               # 随包小工具：拿来就跑，与仓库本身无关
├── scripts/             # 导出、清单、密钥扫描、单文件、打包
└── .github/workflows/   # 提交即校验
```

`skills/`、`scripts/`、`tools/` 的分工：技能讲**怎么做**，`scripts/` 维护**这个仓库**，
`tools/` 是**删掉仓库也照样能用**的独立脚本（目前有 `zip_each` 批量单独压缩，
见 [`tools/README.md`](tools/README.md)）。

## 添加一条想法

```bash
cp context/ideas/_template.md context/ideas/2026-10-22-我的想法.md
# 填 frontmatter + 结论，然后
python scripts/build_manifest.py
```

## 添加/更新一个技能

技能源目录保持在原工具里，导出到本仓库：

```bash
python scripts/export_skills.py            # 全量导出
python scripts/export_skills.py --only ps5 # 只更新一个
```

导出时会自动脱敏内网 IP、本机绝对路径、邮箱与已知凭据。

## 许可

私人知识库，默认不授权外部使用。
