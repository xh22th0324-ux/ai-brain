# PPTX 设计指南（zagens-office）

> 写正式 deck JSON **之前**读本文件。这是 Agent 自检清单，不是引擎硬失败条件。  
> 契约与命令仍以 `SKILL.md` + `zagens-office schema write pptx` 为准。  
> **正式 / 精修稿落盘路径（硬）：** 骨架 `write` → **逐页** `upsert_slide`（见 `office-pptx` `SKILL.md`）。禁止一次 `write` 塞满多页重 `elements[]`。

按引擎能力改写：JSON + `theme` / `elements[]` / `master` + 逐页 upsert；不依赖 JSX / STORY 门禁。

---

## 1. 何时读本文件

| 场景 | 是否必读 |
|------|----------|
| 正式商务路演、公司介绍、咨询交付、政务汇报、学术答辩 | **必读** |
| 内部周报、3–5 页速出、纯数据表汇报 | 扫第 2、8 节即可 |
| Word / Excel / PDF | 不读（本文件仅 PPTX） |

像素级 Flex 排版、逐页 JSX 热预览、宿主 STORY/DESIGN 门禁 → 优先宿主高精度路线，勿用本指南硬凑。

---

## 2. 五大原则 → 引擎落点

| 原则 | 要求 | 用什么实现 |
|------|------|------------|
| **一致性** | 色板/字体/页脚全篇统一 | `theme` preset 或六色自定义；`master` 统一页码/品牌 |
| **密度** | 内容页不稀薄；空 ≠ 极简 | 每页一个主论点 + 锚点元素；勿只留标题+两条短 bullet |
| **配图骨架化** | 图/图标承担叙事，禁装饰小贴片 | `image`（本地 path）/ `icon` / 大面积 `shape`；勿在标题旁塞小装饰 |
| **大胆对比** | 每页至少一个视觉锚点 | `kpi_row`、大号 `textbox`、`chart`、`smartart`、`flow` 组 |
| **视觉节奏** | 高潮页与支撑页交替 | 10 页以上至少 2 页「高潮」（大数字/大图/强图表）；相邻页版式不重复 |

---

## 3. 色板与主题

### 3.1 硬习惯（Agent 侧）

- 色彩角色 ≤ 4：背景 / 强调 / 标题 / 正文（对应 `theme` 的 `bg`/`accent`/`title`/`body`；`muted` 作辅）。图表系列与 SmartArt 默认节点另用引擎从 `accent` 发散的 accent1–6，不必手写彩虹色
- 单页换底色用 `slides[i].bg`（`#RRGGBB` 或 `{colors,angle?}` 渐变）写入真正页背景；勿默认铺全屏 shape。文字色仍跟 theme
- **先定 `theme` 再写 `slides[]`**；页面内自定义色尽量取自同一色板，禁临时彩虹
- 自定义色板用对象：`{"bg","accent","title","body","muted","font"}`（均为 `#RRGGBB`）

### 3.2 Preset 选型

| Preset | 气质 | 适用 |
|--------|------|------|
| `consulting` | Navy 权威、白底 | 战略/路演/B2B 咨询 |
| `academic` | 牛津蓝 + 衬线、纸感白 | 答辩、科研、教学 |
| `civic` | 中国红 + 金辅、米黄底 | 政务、国企、党建汇报 |
| `light` | 现代蓝白 | 通用产品/技术介绍 |
| `warm` | 暖橙纸感 | 消费、教育、人文 |
| `minimal` | 近黑白克制 | 极简品牌、设计向 |
| `dark` | 深底青绿强调 | 技术 Demo、夜间演示 |

风格命中时优先用上表 preset，勿再手填一套冲突色。需要品牌色时用**自定义六色对象**覆盖，仍保持 ≤4 主色角色。

### 3.3 反 AI 味（正式 / 精修 = 硬）

引擎能写 ≠ 该用。禁止这些「一看就是生成稿」的套路：

- **禁止**标题下划线、通栏顶栏/底栏、竖向侧边条、卡片单边描边当装饰（`top_bar`/`underline` 仅用户点名报告风才开）
- **禁止**默认蓝白交差、奶油/米色底（`#F5F5DC` / `#FAF0E6` / `#FFF8E1`）；无品牌色用 preset，勿手填泛蓝
- **禁止**全篇纯 `bullets`、相邻页同版式、每页都「三卡横排」凑数
- **禁止**低对比（浅字浅底 / 深字深底）、装饰小贴片、无信息渐变堆砌
- 一色主导约 60–70%，1–2 辅色 + 一枚锐利强调；四色等权 = 未设计

preset 忌口（宜仍用 Action 标题 / 证据 / 中文优先）：`consulting` 忌金红大面积与彩虹图；`academic` 忌营销撞色；`civic` 忌冷暗红乱配与印章式竖排。

---

## 4. 叙事：先大纲，再 JSON

不必落盘 `STORY.md`，但动笔前在上下文中写清。**正式 / 精修 / 对外：写成 Markdown 大纲交给用户，确认后再写 JSON**（用户明确「直接出」除外）：

1. **受众 / 目标 / 页数**（精简 8–12 / 标准 12–20 / 详版 20+）
2. **逐页一句话论点**（封面 → 议程 → 论证 → 总结/结束）
3. **高潮页标记**：哪些页用 KPI/大图/强图表（约 20–30% 页）
4. **版式预算**：相邻页布局类型不重复；全篇纯 `bullets` 页 ≤ 一半

封面可用顶层 `"cover": true` + `title`/`subtitle`；结束页默认 Thank You，不需要时可 `"include_end": false`。

---

## 5. 内容类型 → 元素选型

| 内容意图 | 优先元素 | 避免 |
|----------|----------|------|
| 核心指标 / 里程碑数字 | `kpi_row` | 把数字塞进等宽 bullet |
| 流程 / 步骤 / 循环 / 层级 | `smartart`（`process`/`cycle`/`hierarchy`/…） | 手摆一排小 `shape` 冒充流程 |
| 对比卡 / 图标行 / Logo 墙 | `flow`（`direction: row\|column`） | 手算每个子元素 `x_pct`/`y_pct` |
| 趋势 / 构成 / 对比数据 | `chart` | 大段文字描述本可用图的数据 |
| 二维表 | `table` | 用 bullet 模拟表格 |
| 公式 | `math`（LaTeX 子集 → PNG） | 复杂可编辑 OMML（非本引擎） |
| 代码片段 | `code_block` | 正文等宽糊弄 |
| 链接落地 | `qrcode` | 远程 `url` 图（CLI 不抓取） |
| 说明性配图 | 本地 `image.path`（可 `.svg`→栅格） | 在线 URL、标题旁 装饰小条 |
| 分区色块 / 锚点底 | `shape` + `textbox` | 无信息的渐变堆砌 |

**SmartArt 纪律**：勿设 `style`；勿设 `nodes[].image`；`matrix`/`closed_matrix` 勿设 `headers`（改用 `table`）。写完看 `warnings[]`。

**坐标**：`x_pct`/`y_pct`/`w_pct`/`h_pct` 优先 **0.0–1.0**。`flow` 子项不要写绝对坐标；须显式 `w_pct` 并预算 `Σw + gap×(n-1) < 1`（见 §11.3）。

---

## 6. 版式节奏（可执行版）

把每页标一个「布局标签」（仅规划用，不必写入 JSON）：

| 标签 | 典型构成 |
|------|----------|
| `bullets` | `title` + `bullets`（≤5 条，每条≤20 字） |
| `kpi` | 标题 + `kpi_row` |
| `flow_cards` | 标题 + `flow` 对比/要点卡 |
| `diagram` | 标题 + `smartart` |
| `chart_insight` | `chart` + 短洞察 `textbox`/`bullets` |
| `visual` | 大图 `image` + 侧栏文字 |
| `quote` | 居中大号 `textbox`（金句/结论） |
| `section` | 短标题过渡（字少、锚点大） |

**硬习惯：**

- 相邻页标签不得相同
- `flow_cards` / 等宽多卡全篇 ≤ 2–3 页；高潮页不用「三卡横排」凑数
- 连续 ≥ 3 页纯 `bullets` → 拆出一页 `kpi` / `diagram` / `chart_insight`
- 内容页默认保留页码；品牌条用 `master`（需要时），勿每页手动画不同页脚

画布按 16:9 理解边距：左右约 5–8%（`x_pct`≈0.05–0.08），标题带与内容区勿重叠；自由画布元素 `y_pct` **≥0.20**（默认 title chrome 底约 0.20），避免压住标题区。

---

## 7. 密度与留白

| 页面角色 | 密度期望 |
|----------|----------|
| 封面 / 章节过渡 / 结束 | 可留白；必须有主标题 + 一个主视觉或强色块 |
| 内容·单主题 | 标题 + 正文要点 + **至少 1 个锚点**（图/KPI/图示/图表） |
| 内容·卡片组 | `flow` 2–4 卡；每卡有标题+一句说明，勿空壳图标 |
| 数据页 | 主图占内容区视觉重心 + 一句洞察 |

禁止「均匀稀薄」：元素之间等距空白、却没有任何大锚点。高潮页允许更多留白，但空白应环绕锚点，不是整页发空。

字号层级（约数，写入 `textbox`/`runs[].size` 或依赖主题默认）：

- 封面主标题 ≫ 页面标题 ≫ 卡片标题 ≫ 正文 ≫ 页脚/备注  
- 巨型数据用明显大于正文的字号（KPI 数字交给 `kpi_row`）

---

## 8. 写 JSON 前自检（10 条）

任一条明显失败 → 先改大纲/主题，再 `write`：

1. **Theme 已定**：preset 或六色对象已选，且与场景匹配  
2. **大纲完整**：每页一句话论点；封面/论证/收束齐全  
3. **高潮占比**：约 20–30% 页有 KPI/大图/强图表；高潮页不相邻堆叠  
4. **相邻版式不重复**：布局标签已错开  
5. **纯 bullets ≤ 一半**  
6. **每页有锚点**：非过渡页至少有一个大元素  
7. **元素选型正确**：流程→`smartart`，对比卡→`flow`，指标→`kpi_row`  
8. **色板未越界**：未引入 theme 外临时色（强调色只打在焦点上）  
9. **资源就绪**：图片已是工作区内本地 path；icon 用清单内 id  
10. **交付设置**：`include_end` / `master.page_number` 符合场景（正式稿慎关页码）

---

## 9. 写完后三档验收（正式 / 精修 / 对外 = 硬）

`preflight` 只报几何/语义。`view svg` 是 LayoutIR **线框**（`preview_source=layout_ir`，按种类假色），看不见配色 / 图 / AI 味。正式稿必须打开 PowerPoint / WPS，或 `screenshot`（要无头浏览器）。

```powershell
zagens-office edit --path deliverables/deck.pptx --op preflight --input '{}'
zagens-office edit --path deliverables/deck.pptx --op view --input '{"mode":"svg"}'
# SVG 在 result.metadata.svg；改过的页重跑。气质/配色对着打开的文件查
```

对着线框只核 bbox / 出框。对比度、§3.3、残留占位必须对着**打开的文件**。关注 write `warnings[]`（`smartart_skipped` / `flow_overflow` / `image_skipped` / `pct_clamped`）。`layout_overlap` 已过滤全幅底 / 装饰线 / 字压面板（§11.2）。

---

## 10. 与 Hub / 其它 references 的关系

| 文件 | 职责 |
|------|------|
| `SKILL.md` | 何时调用、CLI 契约、路径选择、授权 |
| **本文件** | 正式 PPTX 的叙事/色板/版式/密度自检；**§11 实战坑点** |
| `pptx-craft.md` | 封面/theme/元素硬限制/修版命令 |
| `schema write pptx` | 字段真源 |

冲突时：`schema` 与 CLI 行为 > `SKILL.md` > 本设计指南。

---

## 11. 实战坑点（写 JSON / preflight）

> 引擎契约细节见 [`pptx-craft.md`](pptx-craft.md)；本节是 Agent 写 deck 时的高频误判。

### 11.1 slide 级 bullets 与图文并排

slide 级 `bullets` / `table` / `chart` 由引擎写入**固定全宽**内容区（约 x=0.09–0.90），**不能**像 `textbox` 那样限宽。

| 页面意图 | 做法 | 避免 |
|----------|------|------|
| 纯文字要点页 | slide 级 `bullets` | — |
| 左文右图 / 左要点右配图 | `elements[].textbox`（`w_pct`≈0.55）+ 右侧 `image`/`shape` | slide 级 `bullets` + 右侧图（必撞 → `layout_overlap`） |

`elements[]` 与 slide 级垂直栈**可同时存在**，但不代表可以混用 bullets 做「半宽列表」。

### 11.2 preflight `layout_overlap`

- AABB 仍报真撞（两卡重叠、文挡文）。全幅底、细装饰条、字压在面板里**不再报**。
- `auto_fix` **不会**移动形状；确认真撞用 `avoid_overlap` 或改坐标。
- **判读**：`view svg` 看 bbox（`result.metadata.svg`）。引擎不走 cairo / cairosvg。配色 / 图要打开文件。

### 11.3 `flow` 子项宽度

row 容器内子项默认**等分**主轴；不写 `w_pct` 时 icon 会被拉成条块。

| 子项类型 | 建议 `w_pct` |
|----------|--------------|
| `icon` | 0.035–0.05 |
| 要点卡 / 小面板 | 0.17–0.20 |

硬约束：`Σw_pct + gap×(n-1) < 1`。超出会 `flow_overflow`（引擎自动缩放，但预算准确更稳）。

### 11.4 配图落盘（CLI）

CLI **不抓取** `url`。先落到 `deliverables/assets/…`，校验文件头（JPEG `ffd8ff` / PNG `89504e47`）并目视；勿仅凭 HTTP 200。`flow.children[]` 项尾 `},`，勿 `} },`。
