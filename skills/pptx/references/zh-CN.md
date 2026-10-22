# pptx 中文指南

## 技能用途与适用场景

处理一切涉及 `.pptx`/`.potx` 的任务：创建幻灯片与路演稿、读取与抽取内容（含演讲者备注）、编辑、合并，以及使用模板与版式。一个 `.pptx` 本质是 XML 文件的 ZIP 压缩包，按任务选方法：

| 任务 | 方法 |
|---|---|
| **创建**新演示文稿 | 写 `pptxgenjs` 脚本（见下方陷阱清单） |
| **编辑**现有文稿 / 基于模板制作 | unzip → 编辑 `ppt/slides/slideN.xml` → zip |
| **读取**内容 | `markitdown deck.pptx`（每张幻灯片一个 `<!-- Slide number: N -->` 块）；看视觉缩略图用 `python scripts/thumbnail.py deck.pptx` |

## 内置脚本用法

| 脚本 | 用途 |
|---|---|
| `scripts/thumbnail.py deck.pptx [prefix]` | 生成每张幻灯片的带标签缩略图网格，用于挑选模板版式。仅支持 `.pptx`。**务必传第二个参数 prefix**（默认 `thumbnails`），否则同目录两个文稿的网格会互相覆盖 |
| `scripts/add_slide.py unpacked/ slide2.xml [--after slideN.xml]` | 复制幻灯片（或 `slideLayoutN.xml`）并完成包内全部登记工作；也可直接对 `.pptx` 用 `-o out.pptx` |
| `scripts/clean.py unpacked/` | 删除不再被引用的幻灯片、媒体与关系文件。**在 `<p:sldIdLst>` 定稿之后运行** |
| `scripts/validate.py deck.pptx [--original src.pptx]` | Schema、关系、内容类型、图表与幻灯片检查，每个失败都给出修复方法。模板衍生的文稿必须传 `--original` 做基线 |
| `scripts/soffice.py --headless --convert-to pdf deck.pptx` | LibreOffice 封装——沙盒中裸调 `soffice` 会挂起 |

## 用 pptxgenjs 创建——关键陷阱

`pptxgenjs` 已预装，**不要先跑 `npm install`**，直接 `require('pptxgenjs')`；仅当 require 失败才安装。

- **先设 `pres.layout` 再加幻灯片**。默认画布 `LAYOUT_16x9` 是 **10" × 5.625"**，不是 13.3" 宽（`LAYOUT_WIDE` 才是 13.3" × 7.5"）。超出边界的坐标会被原样写入而非裁剪，形状直接落到画布外。
- **十六进制颜色：不要 `#`、不要 8 位**。写 `color: "FF0000"`。`"#FF0000"` 或带透明度的 `"00000020"` 都会**损坏文件**。半透明：填充/图片用 `transparency: 0-100`，阴影用 `opacity: 0.0-1.0`——两者互不通用。
- **pptxgenjs 会原地修改选项对象**（首次使用时把值转成 EMU）。绝不在两个 `add*` 调用间共享同一个 shadow/options 对象，每次新建。
- **阴影 `offset` 必须 ≥ 0**，负值损坏文件；向上投影用 `angle: 270` + 正 offset。
- **`letterSpacing` 会被静默忽略**，真正的选项是 `charSpacing`。
- **列表**：每项设 `bullet: true`，绝不用字面 `•`（会渲染双圆点）；除最后一项外每个数组项设 `breakLine: true`；项目符号段落间距用 `paraSpaceAfter`，不用 `lineSpacing`（间距过大）。
- **每个输出文件只 `new pptxgen()` 一次**，绝不复用实例。
- **`rectRadius` 只对 `ROUNDED_RECTANGLE` 生效**，对 `RECTANGLE` 无效。
- **不支持渐变填充**——用渐变图片当背景。
- **文本框自带内边距**——文字要与形状/线条/图标对齐时设 `margin: 0`。
- **演讲者备注用 `slide.addNotes("...")`**（纯文本，每张一次），不要放进幻灯片文本框。
- **图表保持原生**：PowerPoint 能画的都用 `addChart()`（组合图传 `{type, data, options}` 数组）；库没暴露的原生特性（趋势线、误差棒）自己算出额外序列或后处理 OOXML，不要退回贴图片。只有 PowerPoint 没有的图型（Sankey、网络图、和弦图）才用图片。
- **默认图表很朴素**：设 `showTitle` + `title`、`showValue: true` + `dataLabelPosition`、`chartColors: [...]`，并静音边框（`catAxisLabelColor`/`valAxisLabelColor`、`valGridLine: { color, size }`、`catGridLine: { style: "none" }`，单系列加 `showLegend: false`）。
- **堆积图上 `dataLabelPosition` 只能是 `ctr`/`inEnd`/`inBase`**，`outEnd` 会**损坏文件**。
- **组合图使用 `secondaryValAxis`/`secondaryCatAxis` 时，图表选项必须同时提供 `valAxes` 和 `catAxes`（各两项）**。只给 `valAxes` 不够——缺了它们 pptxgenjs 写出未声明的轴 id，PowerPoint 会拒开并报文件损坏。
- **`writeFile()` 之后必须跑 `python scripts/validate.py deck.pptx`**，它专查上述两类图表错误和 PowerPoint 拒收的 XML 缺陷。修复要在生成器里改，不要手改打包后的 XML。
- **绝不重排 `<p:presentation>` 的子元素**。pptxgenjs 把 `<p:notesMasterIdLst>` 紧跟 `<p:sldIdLst>`，PowerPoint 能读；一动顺序同一文件就打不开。
- **图标**：用 `ReactDOMServer.renderToStaticMarkup` 把 `react-icons` 渲染成 SVG，`sharp` 栅格化到 ≥256px，经 `addImage({ data: "image/png;base64," + buf.toString("base64") })` 插入——`image/png;base64,` 前缀必须带上（相关包已预装，require 失败才安装）。

## 编辑现有文稿与模板

先选版式：`python scripts/thumbnail.py template.pptx template-thumbs` 生成缩略图网格并打印文件名（超 12 张会拆成多个 `-N.jpg`）。仅用于模板分析；视觉 QA 需用完整分辨率渲染，且它只认 `.pptx`——`.potx` 要先复制成 `.pptx` 文件名再处理。配合 `markitdown` 把各内容段落映射到模板页，版式要有变化，不要每节都用同一种"标题+项目符号"。

编辑流程：

```bash
python3 -c "import sys,zipfile; zipfile.ZipFile(sys.argv[1]).extractall('unpacked')" deck.pptx
python scripts/add_slide.py unpacked/ slide2.xml --after slide2.xml   # 复制页，打印新页路径
# 排序/删除 = 编辑 ppt/presentation.xml 里的 <p:sldIdLst>
python scripts/clean.py unpacked/                                     # 删除后清理孤儿资源
# 在 ppt/slides/slideN.xml 里编辑内容
(cd unpacked && rm -f ../out.pptx && zip -Xr ../out.pptx .)           # 必须在目录内打包；先 rm 否则已删部分残留
python scripts/validate.py out.pptx --original deck.pptx
```

要点与陷阱：

- **所有结构调整（增/删/排序）必须在编辑内容之前完成**：`add_slide.py` 原样复制页面文件，后复制会克隆你已改的内容；`clean.py` 会删除 `<p:sldIdLst>` 里没有的页，包括你刚写好的。
- **绝不用手工复制幻灯片文件**——`add_slide.py` 会完成新页所需的全部登记（输出如 `Created ppt/slides/slide17.xml from slide2.xml`）。直接对文件操作时**必须传 `-o`，否则原地改写输入文件**。复制的页仍*引用*源页的图表/SmartArt/嵌入对象（不克隆），改一页的图表另一页跟着变。
- **python-pptx 的三个短板**：无法复制幻灯片（只有 `add_slide(layout)`）；`text_frame.text = "..."` 会把段落塌缩成单个无样式 run（应改赋值 `run.text`）；读不了模板插画常用的 SVG/EMF（`add_picture` 抛 `UnidentifiedImageError`）。
- **旧 `.ppt` 先转换**：`python scripts/soffice.py --headless --convert-to pptx file.ppt`。`.potx` 解包打包流程相同，输出保留 `.potx` 扩展名。
- 模板 XML 转换用 `defusedxml.minidom` 解析——`xml.etree.ElementTree` 回写会重写命名空间前缀，损坏文稿。
- **模板槽位 ≠ 素材数量**：模板 4 个成员你只有 3 个时，删掉第 4 个成员的整组（图片+文本框），不只删文字，之后 QA 检查孤儿元素。
- 每个列表项一个 `<a:p>`，绝不拼接成一段；复制同级 `<a:pPr>` 保留间距；标题、节标题和行内标签（`Status:`、`Owner:`）的 `<a:rPr>` 加 `b="1"`。
- 项目符号从版式继承；只在覆盖时加 `<a:buChar>`、`<a:buAutoNum>`（编号）或 `<a:buNone>`，文本里绝不写 `•`。
- 文本首尾有空格时其 `<a:t>` 需加 `xml:space="preserve"`。

## 设计建议

- **配色**：选贴合主题的配色，不要默认蓝。主色占 60-70% 视觉权重，配 1-2 个辅助色 + 一个锐利强调色。可选：Midnight Executive `1E2761`/`CADCFC`/`FFFFFF`、Forest & Moss `2C5F2D`/`97BC62`/`F5F5F5`、Coral Energy `F96167`/`F9E795`/`2F3C7E`、Charcoal Minimal `36454F`/`F2F2F2`/`212121` 等。深色背景用于首尾页、浅色用于内容页（"三明治"结构），或全深色更显高级。
- **视觉母题**：选一个独特元素（圆角图片框、彩色圆圈里的图标）贯穿全篇；**不要用色条/饰条当母题**（见 Avoid）。
- **每页都要有视觉元素**：图片、图表、图标或形状。布局可选双栏、图标+文字行、2x2/2x3 网格、半出血图 + 内容叠加。数据展示可用 60-72pt 大数字标注、对比栏、时间线/流程图。
- **字体**：写入 .pptx 的字体名由用户的 PowerPoint 渲染，QA 预览用 LibreOffice 替代字体，宽度可能不同。安全字体（QA 宽度可靠且 Office 自带）：**Arial, Calibri, Cambria, Times New Roman, Courier New, Bookman Old Style, Century Schoolbook**。标题求个性可用安全衬线 + 安全无衬线正文。用户指定安全列表外字体（如 Georgia、Trebuchet MS、Impact、Arial Black、Garamond、Consolas、Palatino Linotype 等 QA 不可靠字体）时按需使用，但容器留约 10% 余量且不要相信 QA 的文本溢出判断。**绝不默认 Aptos**（新旧两端都不可靠）。
- **字号**：页标题 36-44pt 加粗，节标题 20-24pt，正文 14-16pt，注释 10-12pt 弱化色。
- **间距**：最小边距 0.5"，内容块间距 0.3-0.5"，留白呼吸感。

**Avoid 清单**：不要重复同一布局；正文左对齐（只居中标题）；字号对比要够；配色贴题；间距统一；风格全篇一致；不要纯文字页；对齐时设 `margin: 0`；图标和文字都要高对比；**绝不给标题下加装饰线**（AI 味的标志）；**绝不加横贯色条、边侧竖条、卡片单边饰条**（想突出卡片用浅底色、投影或图标）；不要默认米黄背景（用 `FFFFFF` 或品牌色，避开 `F5F5DC`/`FAF0E6`/`FAEBD7`/`FFF8E1`）；绝不留文字溢出（缩字号、拆页或放大容器）。

## QA（必做）

1. **内容 QA**：`markitdown output.pptx` 检查缺漏、错字、顺序。模板衍生文稿再跑占位符排查：
   `markitdown output.pptx | grep -iE "\bx{3,}\b|lorem|ipsum|\bTODO|\[insert|this.*(page|slide).*layout"`，有结果必须修掉。
2. **文件 QA（必做）**：`python scripts/validate.py output.pptx`；模板衍生必传 `--original src.pptx`（以模板为基线，避免模板自身的 XSD 错误算到你头上；关系/内容类型/图表等结构性检查不受 `--original` 影响，仍需单独审阅）。pptxgenjs 的图表 XML 只有 PowerPoint 拒收，python-pptx 能开、LibreOffice 能渲染、XSD 能过——所以这步必须做。
3. **视觉 QA**：转成图片逐页检查（建议用子代理以"新鲜眼光"看）。最常见缺陷是**文字溢出/被裁切（优先检查）**；其次：元素重叠、脚注/引用碰撞、间距 <0.3"、边距 <0.5"、对齐不一、低对比文字/图标、模板装饰错位、文本框过窄导致过度换行、遗留占位符。

## 转图片与依赖

```bash
python scripts/soffice.py --headless --convert-to pdf output.pptx
rm -f slide-*.jpg
pdftoppm -jpeg -r 150 output.pdf slide
ls -1 "$PWD"/slide-*.jpg   # 把打印出的绝对路径直接交给看图工具
```

`pdftoppm` 按页数补零（<10 页 `slide-1.jpg`，10-99 页 `slide-01.jpg`，100+ 页 `slide-001.jpg`）。**修复后必须重跑全部四条命令**——PDF 要先从改后的 `.pptx` 重新生成，改动能才会出现在图里。

依赖：`pptxgenjs`（npm 预装）· `markitdown[pptx]`、`Pillow`、`defusedxml`、`lxml`（pip）· LibreOffice（经 `scripts/soffice.py` 自动配置）· `pdftoppm`（Poppler）。
