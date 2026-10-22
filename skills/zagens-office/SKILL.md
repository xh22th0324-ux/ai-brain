---
name: zagens-office
display_name: Office 文档引擎
display_name_en: Office Document Engine
description: "凡涉及创建或编辑 Office 文档（.pptx / .docx / .xlsx / .pdf），优先使用本技能。演示文稿/路演/精修 PPT 先 load_skill office-pptx；洗表/拼表走 office-xlsx-data。触发：演示文稿、幻灯片、PPT、公司介绍、路演、报告、提案、表格、电子表格、Word、公式、LaTeX 及各类 Office 文件名。zagens-office 为本机结构化引擎：声明式 JSON 入、schema 校验后秒级出可打开文件。本技能可用时，勿回退去写生成脚本。"
description_zh: "专门为高频使用 PPT / XLSX / DOCX / PDF 的人员准备的技能，内置 Office 引擎，可快速生成、编写、修改各种原生 PPT / XLSX / DOCX / PDF 文档。"
description_en: "A skill for people who work with PPT, XLSX, DOCX, and PDF every day. Built-in Office engine to quickly create, write, and edit native documents."
category: writing
version: 0.12.0
author: Zagens
allowed-tools: Read, Write, Bash
---

# zagens-office：Office 文档生成与编辑

单二进制 CLI，无 Office 依赖。Windows 默认：`~/.zagens-pro/bin/zagens-office.exe`（已在 PATH 时可直接 `zagens-office`）。

**默认只读本文件，不要预读 `references/`。** 本包是 WorkBuddy 市场 Hub。演示文稿 → **`load_skill office-pptx`**（未装则读 @references/pptx-design.md 与 @references/pptx-craft.md）；改已有 XLSX 表单 → @references/xlsx-fill.md（不足再 @references/xlsx-grid.md）；DOCX/PDF → @references/docx-pdf.md。字段以 `schema` 为准。Windows 安装与沙箱细节 → @references/workbuddy-host.md。

## 首次使用（Windows）

本 skill 只有说明，**不含 exe**。引擎在 `~/.zagens-pro/bin/`（**CLI + GUI** 都要装）。

1. **探测**（按当前 shell，勿混用变量）：
   - PowerShell：`& "$env:USERPROFILE\.zagens-pro\bin\zagens-office.exe" --version`
   - Git Bash / 多数 Agent 终端：`"$HOME/.zagens-pro/bin/zagens-office.exe" --version`
   - 已在 PATH：`zagens-office --version`
   - **禁止**在 Bash 里写 `%USERPROFILE%...`。以 stdout 版本号为准，勿凭退出码判断。
2. 探测失败：按 https://zagens.com/download/install.md（备用：https://raw.githubusercontent.com/didclawapp-ai/zagens-office/main/install.md）执行 **§1–§3**（下载 CLI+GUI、SHA-256、`--version`）。**不要**跑 `zagens-office integrate`——会覆盖本市场技能。
3. **沙箱**（出件前必做一次）：在本技能目录执行  
   `powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/ensure-workbuddy-sandbox.ps1`  
   脚本把 `~/.zagens-pro` 幂等写入 `~\.workbuddy\settings.json` 的 `sandbox.extraAllowWrite`（改前备份、UTF-8 无 BOM）。详见 @references/workbuddy-host.md。
4. 装完再 `--version`。评估期 90 天；`license_locked` 后走 `license contact` → `license activate --key`。

非 Windows：先告诉用户当前发行以 Windows x64 为主，再停下；不要假装已安装。

## §0 · Skill 路由（Hub + Spoke）

| 用户意图 / 信号 | 加载 | 入口 |
| --- | --- | --- |
| 演示文稿 / 幻灯片 / 路演 / 精修 / 改 PPT / 填模板 / 拆合页 | **`load_skill office-pptx`** | 独立包；先锁定新建/填壳/美化/增强；正式稿确认大纲；`view svg` 只是线框 |
| 8D / 巡检 / merge 企业模板 / fillmap | **留本 skill** | `read fillmap` → `edit fill`；未覆盖格见 @references/xlsx-grid.md |
| 洗订单/名单/台账、去重、统一格式、clean_report | **`load_skill office-xlsx-data`** | 独立技能；清洗见该 skill `references/clean.md` |
| 多文件/多 Sheet 合并、拼表、归档、`merge_report` | **`load_skill office-xlsx-data`** | 合并见该 skill `references/merge.md` |
| 从 CSV 做带样式**新报表**（无清洗管道） | 本 skill | `write xlsx-table` / `source` |
| 课件 / 公开课 / 说课 / 教案PPT / 家长会PPT | **另装 `office-kejian`** | 出件仍走本引擎 |

## 通用纪律（四格式共用）

1. **先契约**：`schema write <pptx|xlsx|docx|pdf>` 或 `schema edit`（100 op，不可按格式过滤）。
2. **信封**：stdout 一行 JSON；`ok=false` 时按 `code`/`error`/`suggestion` 修正，勿盲目重放。
3. **复杂 JSON 用文件**：`--input-file <file>`；简单才 `--input '<json>'`。
4. **多步改稿**：`edit --op batch` + `"atomic": true`；失败看 `result.rolled_back`。白名单含 `fill` / `upsert_slide` / `add_sheet` / `set_text` / `set_props` / `add_slide` / `delete_slide`；`preflight` / `auto_fix` / `fit_text` / `avoid_overlap` / `align` / `distribute` / `snap_to_grid` / `generate_variants` / `rank_variants` / 动画 / 切换 **不在** batch。完整名单以 `schema edit` 为准。
5. **交付自检**：`preflight`（版式/语义）或至少 `validate`（仅 OPC）。**不对 PDF 跑 validate**。
6. **路径**：Windows 用正斜杠或整段加引号。远程 `url` CLI **不抓取** → 本地 `path`。
7. **授权**：期满 write/edit → `license_locked`。跑 `license contact`，按 `banner_markdown` 打开授权页后 `license activate --key`。`read`/`schema`/`license`/`update` 不锁。

| 命令面 | 用法 |
|--------|------|
| 生成 | `write {pptx\|xlsx\|xlsx-table\|docx\|pdf} --path <out> ...` |
| 编辑 | `edit --path <file> --op <op> ...` |
| 读取 | 改前先读再 batch / preflight |

## 1. PPTX

**转 `office-pptx`。** 本 skill 不展开创作 DSL。先锁定新建/填壳/美化/增强。正式/精修：先确认大纲；禁止一次 `write` 塞满重 `slides[]`；`view svg` 只核 bbox，正式/对外打开文件。未装 spoke 时读 @references/pptx-design.md 与 @references/pptx-craft.md。

## 2. XLSX

**入口**：`write xlsx` / `write xlsx-table` · `edit`（含 **`op: fill`**）· `read xlsx --mode table|grid|fillmap|fields`。写 grid/html 常需 `--workspace .`。

| `layout` | 用途 |
|----------|------|
| `table`（**默认**） | 数据表/清单 |
| `grid` | 精确版式 / `sections` 表单 |
| `html` | 模型友好 HTML `<table>` → 同 grid |
| `template` / `promote` | 模板填值 / 入库（见 schema） |

多 Sheet：第 1 张 `write`；后续 `edit --op add_sheet`（可进 `batch`）。勿同 path 反复 `write` 覆盖。复杂新建先 `--validate-only`，细节见 @references/xlsx-grid.md。

**改已有表单（首选）：** `read --mode fillmap` → `edit --op fill`（≥20 格先 `"dry_run": true`）。流程见 @references/xlsx-fill.md。

## 3. DOCX · 4. PDF

- **DOCX**：`write docx` · `edit` · `read --mode outline|text|stats`。`sections[]` 与顶层 `blocks[]` 互斥。见 @references/docx-pdf.md。
- **PDF**：几乎只有 `write pdf`。**无** `read pdf`，**不要**对 `.pdf` 跑 `validate`。

## 跨格式备忘

- `schema write` 不含 Pro vault 字段；抄来的 `data_ref` 等会被忽略。
- 不确定字段 → 跑对应 `schema write <format>`，不要把四格式字段混用。
