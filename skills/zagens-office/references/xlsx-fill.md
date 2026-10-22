# XLSX 语义填表（fillmap → fill）

> 改**已有**表单 / 8D / 巡检模板时**先读本文件**。坐标层兜底见 [`xlsx-grid.md`](xlsx-grid.md)。  
> 字段真源：`zagens-office schema write xlsx` / `schema edit`。

## 1. 读：按目标选 mode

| 目的 | Mode / op |
|------|-----------|
| 扫结构 / 中文可读 | `table`（默认）。勿对大表先 full grid 再 head |
| **改已有表单 / 语义填值（首选）** | `fillmap`（推导 `key`→`ref`）→ `edit --op fill` |
| **改已有模板 / 要坐标（兜底）** | `grid`（默认 **compact**）→ 见 `xlsx-grid.md` |
| **`{{field}}` 占位 sidecar（legacy）** | 才用 `fields`（读 cell→key；**≠ fillmap**） |
| 同文件二次填表 | `{stem}.fields.json`（`schema_version: 2`）旁路 sidecar，`fill` 直读 |
| `.xls` / `.xlsb` / `.ods` | 只用 `table`；grid/fillmap 硬拒（另存 `.xlsx`） |

**三种「字段」机制勿混用**

| 机制 | 读 | 写 | 映射方向 |
|------|-----|-----|----------|
| **`fillmap`** | `read --mode fillmap` | — | 标签推导 **key→ref** |
| **`op: fill`** | sidecar v2 或 fillmap | `fields:{ "键": 值 }` | **key→value**（零坐标） |
| **`mode: fields`** | legacy sidecar / `{{key}}` | `layout:template` | **cell→key**（模板占位） |

## 1.1 fillmap 前置条件（重要）

- **适用：** 合并单元格表单（标签格 + 值格，如 8D / 巡检模板）。推导依赖合并区结构。
- **不适用：** 无合并的简单「标签列 | 空白值列」两列表——`fillmap` 会返回 `fields: []`（**设计行为，非缺陷**）。此类表请用 [`xlsx-grid.md`](xlsx-grid.md) 的 `set_cell` / `set_range`（可用 `sheet` + 裸 `A1`）。

## 2. 标准流程（复杂合并表 / 8D / 巡检）

1. `read xlsx --mode fillmap --path FILE.xlsx` — 列出 `key`、`ref`、类型；`unmapped_empty_cells` 如实暴露未推导格
2. 复杂表（≥20 需填格）：`edit --op fill` + `"dry_run": true`，审 `report`（与 batch dry_run 同构信封）
3. 冲突 → `fill_key_conflict` + 候选列表，**整 op 不写入**；未命中 → `fill_key_not_found` + 编辑距离 ≤2 的相近 key
4. 修正 `fields` 后正式 `fill`（`"atomic": true`，去掉 `dry_run`）；关键字段可附 `"assert": { "require": ["键1","键2"] }`（缺键 → `contract_violated`；`mode:"warn"` 则继续填并出 `fill_contract` 警告）
5. 同目录 `{stem}.fields.json`（`schema_version: 2`）存在时，`fill` **直读 sidecar**，跳过 fillmap；消歧后可沉淀 `key_aliases`
6. fillmap/sidecar **未覆盖**的少数格 → [`xlsx-grid.md`](xlsx-grid.md) 坐标层单格补写
7. **复杂合并表交付前仍须** `edit --op view --input '{"mode":"html"}'` 目视

```powershell
zagens-office read xlsx --path FILE.xlsx --mode fillmap
zagens-office edit --path FILE.xlsx --op fill --input '{"fields":{"报告编号":"8D-001","D3.措施1":"已隔离"},"dry_run":true}'
zagens-office edit --path FILE.xlsx --op fill --input-file fill.json
# fill.json: { "fields": { ... }, "atomic": true }
```

- `fill` 也可作为 `batch.ops[]` 一步（白名单内）；**非**独立 BatchOp 枚举，而是 replay 前把 `{ op: fill }` **展开为 `set_cell` 序列**；`dry_run` 审展开后的 `diffs` + `context_preview`（±2 行局部网格）
- `promote` 可选 `"sidecar_version": 2` 将 legacy cell→key 转为 v2 key→ref

## 3. 语义层禁区

- 禁止对可 fill 的字段 **手算 excel_ref / at 行号**
- 禁止混淆 **`fillmap` / `op: fill` / `mode: fields`**
- 禁止对 20+ 格复杂表 **跳过 fill dry_run** 直接正式写
- fillmap 覆盖率不足时 **不得强行 fill 全覆盖** — 未覆盖格走坐标层或上报用户
