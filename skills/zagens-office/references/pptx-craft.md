# PPTX 创作契约（zagens-office）

> 写页 JSON / `upsert_slide` **之前**读本文件。设计原则与自检见 [`pptx-design.md`](pptx-design.md)。  
> 字段真源：`zagens-office schema write pptx`。落盘路径见 `office-pptx` `SKILL.md`。

## 1. 封面 / 页码 / 主题

- **`title` ≠ 封面**：默认 `cover:false`；要引擎封面页须 `cover:true`，否则封面内容写进 `slides[0]`（可 `title_style.engine:false` 自绘）。精修稿封面优先自绘 `slides[0]`，少用默认居中 cover。
- **标题 chrome**：默认仅粗体标题，**无**顶栏/下划线；要报告风须显式 `top_bar`/`underline`（经 `content_title_style`、`master.title_style` 或单页 `title_style`）。自由画布精修页常用 `"title_style":{"engine":false}`。
- **页码**：省略整个 `master` → 内容页默认小字 `n/total`；**一旦写了 `master`，`page_number` 默认 false** → 要页码须显式 `"page_number": true`。`include_end:false` 去掉 Thank You。
- **theme**：preset 字符串，或自定义对象 **六项全必填** `bg/accent/title/body/muted/font`。Preset：`consulting`/`academic`/`civic`/`light`/`warm`/`minimal`/`dark`。单页可写 `slides[i].theme`。
- **图表 / SmartArt 色**：系列与节点默认跟主题 **accent1–6**。`accent1` = 品牌 `accent`；非默认主题会自动发散 2–6 色。SmartArt 可用 `style.fills` 覆盖；图表暂无稳定的 `series[].color`。
- **单页背景 `bg`**：`"#0B1F3A"` 或 `{"colors":["#0D1B2A","#C9A84C"],"angle":90}` → 真正的页面 `<p:bg>`。只改背景，不改文字色；优先级 `slide.bg` > `slide.theme.bg` > 整份 `theme.bg`。勿铺全屏 shape 冒充底色（除非要遮罩）。
- **`transition`/`anim` 在 write 无效** → 用 edit（`set_transition`/`add_animation`）；会 `write_field_ignored`。`set_transition` 含 `morph`（AlternateContent + fade fallback）。

## 2. 元素限制速查

| 元素 / 能力 | 支持 | 硬限制 / 易错 |
|-------------|------|----------------|
| `bg`（页背景） | 纯色 `#RRGGBB`；渐变 `{colors,angle?}` | 只改 `<p:bg>`，不改文字色 |
| `theme`（单页） | preset 或六色对象 | 六色全必填；可与 `bg` 并用（`bg` 优先） |
| `textbox` / `shape` | fill 纯色/渐变、radius、shadow、opacity | 渐变语法同 `bg` |
| `image` | **本地 `path`**（工作区内） | CLI **不抓** `url`；先落盘再引用 |
| `icon` | 内置 id 或自定义 `path`/`path_d` | 未知名跳过并附清单；勿猜近义词 |
| `flow` | 子：`textbox\|shape\|icon\|image\|flow` | 子项**勿**写 xy；须显式 `w_pct`；Σw+gap×(n-1)<1；嵌套≤8 |
| `smartart` | 原生 DiagramML | **无**形状回退；勿 `nodes[].image` / `shape_3d` / matrix `headers` |
| `connector` | `straight`/`elbow`/`curve` | 端点坐标或同页 `name` |
| `kpi_row` / `chart` / `table` | 见 schema | 水平柱用 `bar_horizontal`；无 `type:"timeline"` |
| `qrcode` / `code_block` / `math` | 嵌入 PNG | math=LaTeX 子集，非 Word OMML |
| `.svg` | 栅格成 PNG 再嵌 | 依赖系统字体渲中文 |

**远程图（CLI）：** ImageGen / 下载 → 保存到工作区 → **校验文件头**（JPEG `ffd8ff`）并 `Read` 目视，勿仅凭 HTTP 200 → JSON `"path":"deliverables/assets/hero.png"`。Pro 桌面才预取 `url`；CLI 写 `url` → `image_skipped`。

## 3. 版式与元素易错

- **`elements[]` 类型**：`textbox` · `shape` · `image` · `icon` · `kpi_row` · `flow` · `smartart` · `chart` · `table` · `connector` · `qrcode` · `code_block` · `math`。
- **层叠与撞版**：slide 级 `bullets`/`table`/`chart` 先占垂直栈（全宽，约 x≈0.09–0.90，**不可限宽**），再叠 `elements[]`。**图文并排勿用 slide 级 `bullets`**——左侧用 `elements[].textbox`（`w_pct`≈0.55）。`elements[].chart|table` 不占垂直栈。
- **标题区**：默认 chrome 底约 y_pct≈0.20 → 自由画布 `y_pct` **≥0.20**（`title_style.engine:false` 时按实际 bbox）。
- **preflight `layout_overlap`**：AABB 会报真撞；全幅底 / 装饰线 / 字压面板已过滤。`auto_fix` **不会**移动形状。先 `view svg` 核 bbox（`result.metadata.svg`，线框）；确认真撞再 `avoid_overlap`。
- **坐标**：`x_pct`… 首选 **0.0–1.0**；也接受 `(1,100]`；越界 → `pct_clamped`。
- **chart**：水平柱须 `bar_horizontal`（或 `bar_h`）；裸 `bar`/`column` = **竖柱**。另有 `line`/`pie`/`stacked_bar`/`stacked_bar_pct`/`area`/`scatter`/`donut`/`combo`/`radar`/`waterfall`（桥接柱近似）。类目轴 `categories[]`（别名 `labels[]`）。完整枚举见 `schema write pptx`。
- **flow**：子项字段 `children[]`（别名 `items[]`）；仅 `textbox|shape|icon|image|flow`；**子项勿写 xy**；row 默认等分——icon `w_pct` 0.035–0.05，卡片 0.17–0.20；`Σw_pct + gap×(n-1) < 1` 否则 `flow_overflow`；嵌套 ≤8。流程图用 `smartart`，等分 KPI 用 `kpi_row`。`children[]` 项尾是 `},` 而非 `} },`。
- **connector**：真 `p:cxnSp`；端点坐标或 `from`/`to`（`from_name`/`to_name`）指向同页 `name`。编辑侧也可 `op:add` · `element_type:connector`。
- **name / hyperlink**：`textbox`/`shape` 可设 `name`；`hyperlink`：`{url}` 或 `{slide:N}` + 可选 `tooltip`。run 级也支持。
- **SmartArt**：约束未命中 → **不渲染**（`smartart_skipped`）；未知 `layout` → fallback `process` + `smartart_layout_fallback`。勿 `shape_3d`/`scene_3d`/`nodes[].image`；`matrix`/`closed_matrix` 勿 `headers`。

| `layout` | 别名（节选） | 节点约束（摘要） |
|----------|--------------|------------------|
| `process` | `horizontal_process` / `h_process`；竖向 `vertical_process` | 3–7 扁平 |
| `process_alt` | `chevron` / `accent_process` | 3–7 扁平 |
| `hierarchy` | `org` / `horizontal_hierarchy` / `vertical_hierarchy` | 2–12、树深 ≤4 |
| `table_hierarchy` | `table_org` | 2–12、无 assistant |
| `balance` | `compare` | 1 根 + 恰好 2 叶 |
| `cycle` / `block_cycle` | `ring` / `cycle_block` | 见 schema |
| `matrix` / `closed_matrix` | `grid` / `matrix1` | 无 headers |
| `pyramid` / `relationship` / `venn` / `list` / `honeycomb` / `gear` / `arrow_ribbon` / `funnel` | `radial`/`hex`/`cards`… | 节点数随布局变 |

- **icon**：清单内 id；勿猜近义词；可 `path`/`path_d`。
- **富文本 / 媒体**：`runs[]` 支持 `shadow`、渐变 `fill`、超链接；图片 path 用工作区（`--workspace`），与 DOCX/PDF「相对输出目录」不同。

## 4. 自检与修版

正式 / 精修 / 对外：**先 `preflight` 再 `view`（`mode:svg`）核 bbox**；线框不是成品。气质 / 配色必须打开文件或 `screenshot`。改过的页重跑。

```powershell
zagens-office edit --path deliverables/deck.pptx --op preflight --input '{}'
zagens-office edit --path deliverables/deck.pptx --op view --input '{"mode":"svg"}'
zagens-office edit --path deliverables/deck.pptx --op auto_fix --input '{"apply":false}'
# 确认后把 result.plan 原样回放（可选 strict）；溢出/重叠用独立 op
zagens-office edit --path deliverables/deck.pptx --op fit_text --input '{"targets":["/slide[1]/shape[1]"]}'
zagens-office edit --path deliverables/deck.pptx --op avoid_overlap --input '{"targets":["/slide[1]/shape[1]","/slide[1]/shape[2]"]}'
zagens-office edit --path deliverables/deck.pptx --op align --input '{"targets":["/slide[1]/shape[1]","/slide[1]/shape[2]"],"alignment":"left"}'
zagens-office edit --path deliverables/deck.pptx --op snap_to_grid --input '{"targets":["/slide[1]/shape[1]"]}'
```

剩下的 `layout_overlap` 先对线框，勿盲目 `avoid_overlap`。`preflight`/`view`/`fit_text`/`avoid_overlap`/`align`/`distribute`/`snap_to_grid`/动画/切换 **不在** batch 白名单。`role`/`thesis` 在 write 静默忽略；`upsert_slide` 写入备注。
