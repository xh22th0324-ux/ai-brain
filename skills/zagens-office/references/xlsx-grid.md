# XLSX 坐标层与新建 grid

> fillmap/sidecar **未覆盖**、必须指定 `excel_ref`、或新建复杂 grid 时读本文件。语义填表首选 [`xlsx-fill.md`](xlsx-fill.md)。
>
> **`write xlsx` / `xlsx-table` 的 `title`：** 会写入合并标题行（第 1 行），列名表头在第 2 行，数据从第 3 行起。后续 `merge` / `transform` 须设 `header_row: 2`（无 `title` 时仍为 `header_row: 1`）。
> 字段真源：`zagens-office schema write xlsx` / `schema edit`。

## 1. 新建：layout 与校验

Hub 已列 `table` / `grid` / `html` / `template`。复杂报表：

1. 先 `write xlsx --validate-only`（或 JSON `"validate_only": true`）同源校验（**不落盘、无需 `--path`**），按 `issues[]` 修到 `valid:true` 再正式 write。
2. 合并区只在**左上角锚点**写内容；`merge_covered_cell` 指出真实锚点（如 `[3,2]`）。
3. JSON 字符串必须用 ASCII `"`；中文弯引号 `“”`/`‘’` 会导致解析失败。
4. 400+ 格复杂表单：用脚本生成 grid JSON；`sections` 适合中小型表单块。
5. **坐标**：`cells[].at` 为 **0-based**；公式 A1 为 **1-based**（`at:[12,5]` → `F13`，写 `F12` 会报 `formula_row_off_by_one`）。`sections` 勿占同一行（`sections_row_collision`）；data 区公式勿引用 sections 行（`formula_sections_row_ref`）。
6. **跨表公式**：中文或含空格 sheet 名须 `'资产负债表'!F13`（`formula_sheet_needs_quotes`）；未实现函数报 `formula_unknown_function`。
7. **公式重算**：`table`/`grid`/`html`/`template` write 后会内置重算常见函数；财务函数须 Excel/WPS 打开或 COM 冒烟。

- **闸门**：chart 必填 `values_range`；`formula` 与 `text`/`value` 互斥；合并区内勿再放独立 `cells[]`。
- **table 模式字段**：`sheets[].columns[].label` + `sheets[].rows`（或 `source`）；`sheets[].header` 是 **bool**，**不是**列名数组。
- **sections 层级**：`grid.sections` 是**对象**（非数组）；已知键仅 `title` / `meta_row` / `header_row` / `footer` / `data_grid`；`fields`/`fields.rows[]` 在 **sheet 级**；`data_grid` 在 `sections` 内。

写 grid/html 常需 `--workspace .`。

## 2. compact grid 读

| 字段 | 含义 |
|------|------|
| `excel_ref` | A1 坐标，**直接复制**用于 `set_cell` / batch `target` |
| `role` | `anchor`（merge 锚点，附 `merge:"A1:C1"`）或 `value` |
| `merges[]` | sheet 级 A1 范围；**无 covered 占位格** — B25 在 A25:C25 内 → 写 **A25** |
| `at` | 0-based `[row,col]`，**禁止**手算 `at+1` 当 Excel 行号 |

- 大表续读：`grid` + `--start-row N --limit M`（只过滤 `cells[]`，**`merges[]` 全量**）
- 完整样式 IR：`grid --full-style`（**只补样式**，不改变 cells 集合）
- 只要合并区：`edit --op list_merges`
- **compact ≠ 少格子**：`page_cells=0` 时先查分页是否错位，**不要**误以为要改 `--full-style`
- **日期格**：compact 保留 `style.number_format`；`read --mode table` 会把日期序列格式化为日历。`set_cell` **不继承**相邻格格式，裸数字格须补 `set_number_format`

## 3. 坐标层改模板（兜底）

**何时：** fillmap/sidecar 未覆盖；极简单格修改；必须精确 `excel_ref`。复杂合并表 ≥20 格若走本层，**必走 dry_run**。

1. `read xlsx --mode grid --path FILE.xlsx`（大表加 `--start-row` / `--limit`）
2. 必要时 `edit --op list_merges`
3. `edit --op batch --input-file batch.dry.json`（**`"dry_run": true`**，审 `report.diffs` + `context_preview`；非锚点误写须见 `merge_redirect` / `suggested_target`）
4. 按 `suggested_target` 修正后 `"atomic": true` **正式写**
5. `read grid` 抽查；**复杂合并表交付前必须目视**
6. `table` 仅作数据清单，**不是**填表坐标图

```powershell
zagens-office edit --path FILE.xlsx --op view --input '{"mode":"html"}'
```

**禁区：** 禁止用 `at` **+1 心算** Excel 行；禁止把 `table` 拍扁当坐标图；禁止 20+ 格跳过 dry_run；禁止跳过 view html 即交付。

## 4. 写 grid / 编辑深化

- 数字格：`value`/`number`；超链接：`hyperlink`（与 formula/value/number 互斥）；`style.format`≡`number_format`；`border:"none"`；sheet `name`≤31；`style.theme` 仅 `corporate|tech|warm|minimal`。
- `set_range` 的 `target` 是**起始格**，不是 `A1:B2`。
- 图 `add_image`；legacy 批注（threaded 硬拒）；命名区域（`_xlnm.*` 删需 `force`）。
- 插删行列：平移 merge/CF/公式/table/cell-anchor drawing/批注/本 sheet 名；纯 `absoluteAnchor` 放行；shared·array / 混锚点 / pivot / threaded **硬拒**。
- `auto_fix`：结构兼容，**不是**视觉排版。

```powershell
zagens-office write xlsx --path deliverables/book.xlsx --workspace . --input-file sheet1.json
zagens-office edit --path deliverables/book.xlsx --op add_sheet --input-file sheet2.json
zagens-office read xlsx --path deliverables/book.xlsx --mode grid --start-row 0 --limit 500
zagens-office edit --path deliverables/book.xlsx --op batch --input-file batch.dry.json
zagens-office edit --path deliverables/book.xlsx --op view --input '{"mode":"html"}'
```
