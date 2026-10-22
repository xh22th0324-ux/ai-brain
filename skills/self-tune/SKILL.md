---
name: self-tune
description: 本机 WorkBuddy 与 Windows 环境的「一键体检 + 自动调参」技能。当用户说「把你自己设置一下」「这些选项设置好」「环境体检 / 看看有没有要调的」「缓存目录改到 X 盘」「本地技能与记忆沉淀开了没 / 打开它」「默认工作区换到哪」「沙箱 / Agent Teams 开关」「记忆生成开关」「语气风格」等时使用。它按预期清单逐项比对实际配置（用户级 TEMP/TMP 环境变量、app-config.json、settings.json、技能目录、归档共享），给出差异表，并在确认后一次性改好、自动备份、留变更日志。凡涉及「这台机器该怎么配才对」的重复性问题，优先调用本技能而不是临时手改。
description_zh: 本机环境体检与自动调参：缓存盘、记忆沉淀、本地技能、工作区等一次性设好
version: 1.0.0
agent_created: true
---

# self-tune — 本机环境体检与自动调参

一句话：**先体检（只读），再确认，再改**。所有改动都落在这台机器的固定几处，改前自动备份，改后留日志。

## 什么时候用

| 用户说的话 | 走哪一步 |
|---|---|
| 「检查一下 / 看看有没有要调的 / 体检」 | `check`（默认，只读） |
| 「把你自己设置一下 / 这些选项都设好」 | `check` → 给差异表 → 确认 → `apply --yes` |
| 「缓存改到 D 盘」这类换目标盘的诉求 | 改 `config/expected.json` 的 `temp_dir` 或 `--temp-dir` 覆盖，再 `apply` |
| 「本地技能与记忆沉淀打开没」 | `check --only local_skills_memory`，然后念结论 |
| 「为什么改完没生效」 | 看下面「生效条件」三条，八成是没重启或被界面覆盖 |

## 一键用法

```bash
# 只读体检（永远先跑这个）
python <SKILL_DIR>/scripts/self_tune.py check

# 机器可读
python <SKILL_DIR>/scripts/self_tune.py check --json

# 只看某一项（逗号分隔）
python <SKILL_DIR>/scripts/self_tune.py check --only temp_dir,local_skills_memory

# 真改（不带 --yes 只打印计划，不动手）
python <SKILL_DIR>/scripts/self_tune.py apply --yes
```

退出码：`0` 全部符合 / `1` 有差异（待处理）/ `2` 执行出错。

## 清单：都有哪几项、存在哪、默认是什么

| 键 | 位置 | 默认 | 含义 |
|---|---|---|---|
| `temp_dir` | 注册表 `HKCU\Environment` 的 `TEMP`/`TMP` | `%LOCALAPPDATA%\Temp` | 所有进程的临时目录。放小盘容易满 |
| `local_skills_memory` | `<root>\app\app-config.json` → `disableLocalSkillsMemory` | 未设 = **开** | 「本地技能与记忆沉淀」总开关。**存的是"禁用"**，`false` 才是开 |
| `memory_generate` | `<root>\settings.json` → `generateMemoryEnabled` | 未设 = **开** | 云端生成记忆档案（memory profile） |
| `local_memory` | `<root>\settings.json` → `localMemoryEnabled` | 未设 = **关** | 本地记忆档。清单里写 `null` = 只报告、不擅自改 |
| `default_workspace` | `app-config.json` → `defaultWorkspacePath` | `~\WorkBuddy` | 新会话默认工作区 |
| `locale` | `app-config.json` → `locale` | `zh-CN` | 界面语言 |
| `tone_style` | `app-config.json` → `personalization.toneStyle` | `professional` | 语气风格 |
| `sandbox_safety` | `app-config.json` → `sandboxSafetyEnabled` | 未设 = **开** | 沙箱安全策略 |
| `agent_teams` | `app-config.json` → `disableAgentTeams` | 未设 = **开** | 多 Agent 协作（存的是"禁用"） |
| `skills_dir` | `<root>\skills` | — | 本地技能目录，只检查不修 |
| `skills_archive` | `\\iStoreOS\games\skills` | — | 技能归档共享，只探测可达性 |

`<root>` = `C:\Users\<你>\.workbuddy`。

> ⚠️ 注意「存反值」的两个：`disableLocalSkillsMemory` 和 `disableAgentTeams`，`false` 才代表功能**开着**。脚本已经帮你翻了，别看错。

## 生效条件（三条，改完必须说清楚）

1. **环境变量只对新进程生效** —— WorkBuddy 必须重启，`os.environ["TEMP"]` 才会变。
2. **`app-config.json` 在启动时被读取** —— 程序若正在运行，退出时可能回写覆盖；保险做法是**先退出 WorkBuddy 再 apply**。
3. **界面开关是权威** —— `settings.json` 里那两个记忆键是同一份配置的另一入口。若 apply 后界面上没跟着变，以界面为准并说明原因，别硬改第二遍。

## 输出怎么讲给用户

- 先一句结论：「N 项里 M 项不符合预期」，再给差异表（项 / 现值 / 期望 / 影响）。
- 涉及重启才能生效的，明确说「现在这一轮还不会变」。
- 备份目录与日志路径要报出来，用户想回退能直接找到。

## 安全边界

- **不删任何文件**，只写配置和环境变量。
- 改前把目标文件整份备份到 `<root>\tools\self_tune_backups\<时间戳>\`。
- JSON 解析失败就停手报错，绝不覆盖成空对象。
- `local_memory` 期望值为 `null` 时，只报告不动手。
