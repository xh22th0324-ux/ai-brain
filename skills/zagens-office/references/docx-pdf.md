# DOCX / PDF 要点（zagens-office）

> Hub 已给入口命令。字段真源：`schema write docx` / `schema write pdf` / `schema edit`。

## 1. DOCX

**入口**：`write docx` · `edit` · `read docx --mode outline|text|stats` · `--preview` / `view svg`（结构预览，**非**分页）。

- `read --mode text` → `result.text`；`stats` 页数是启发式，**非** Word 精确页数。
- 图片 path：相对**输出文件目录**（绝对 / `..` 被拒）。
- **`sections[]` 与顶层 `blocks[]` 互斥**（硬失败）。多分节：每节自有 `page`/`header`/`footer`/`blocks`；省略的 header/footer **继承上一节**。
- 可用：`watermark`、活 TOC（`type:toc`）、`paragraph.page_break_before` / `page_break`、表格 `colspan`/`rowspan`、`textbox`/`shape`、**`code_block`**（`content`/`text`/`code` + 可选 `language`；别名 `type:"code"`）。
- chart：`{"type":"chart","kind":"bar",…}`——**勿重复 `"type"`**；缺 `kind` → 默认 bar + 警告；类目可用 `categories` 或别名 `labels`。
- 非法 `page` / `table.rows` → `page_fallback` / `table_rows_ignored`；未知 `blocks[].type` 会附 did-you-mean。
- `read --mode outline|text` 按 body 顺序包含 **表格**（`kind:table`）。
- `set_props` bold/color → run `/p[N]/r[M]`；`add_table_row` 用 `cells`；插表后路径位移。
- `merge_cells`：表尚无 merge 时可用；被吞格须空。另有 `fill_sdt`、`merge`（`{{key}}`）、`add_caption`/`add_ref` → `schema edit`。
- `auto_fix`：结构兼容，**不是**视觉排版。分栏 / `column_break` JSON **尚未暴露**。

```powershell
zagens-office write docx --path deliverables/report.docx --input-file doc.json
zagens-office read docx --path deliverables/report.docx --mode outline
zagens-office edit --path deliverables/report.docx --op preflight --input '{}'
```

## 2. PDF

**入口**：几乎只有 **`write pdf`**。CLI **无** `read pdf`，也**不要**对 `.pdf` 跑 `edit validate`（读/检用桌面 `read_office`）。

- 可用：段落/标题/简单表/图片、`page_break`、**静态** `toc`（页码列表）、对角 `watermark`。
- **跳过（`unsupported_elements`）**：`chart` / `textbox` / `shape` / `column_break`——要图表用 DOCX/PPTX。
- **TOC 语义**：PDF = 静态页码；DOCX `type:toc` = 活域——勿混用预期。
- 图片 path：同 DOCX（相对输出目录）；远程 url 不抓取。

```powershell
zagens-office write pdf --path deliverables/brief.pdf --input-file brief.json
```
