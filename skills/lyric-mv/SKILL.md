---
name: lyric-mv
description: "从一首 MP3 + 一份歌词原文，做出音画对齐的完整歌词动画 MV（可编辑交付 MP4）。当用户给歌曲/音频并要求配歌词做动画、歌词视频、歌词 MV、音乐短片、lyric video 时使用。覆盖：从音频自动推歌词时间轴、生成场景背景画面、动态歌词排版、ffmpeg 合成整首歌。" 
agent_created: true
---

# 歌词动画 MV

输入一首歌 + 一份歌词文本，输出**整首歌长度、音画严格对齐**的竖屏或横屏 MP4。

核心难点不是画面，是**时间轴**。99% 的失败来自歌词对不上。

## 开工前必须确认的三件事

用 `AskUserQuestion` 一次问完，别逐个追：

1. **交付方式** —— 这决定整个路线，不能猜：
   - 本地合成（设计驱动）：整首歌完整覆盖、音画严格对齐、快、可返工。**默认推荐**。
   - AI 生成短片（Miora）：画面最电影感，但一次只有 3–10 秒、**不带音频、无法覆盖整首歌**，用户得自己剪。
   - 混合（推荐给追求效果的）：AI 生成场景图当画面素材，再用 ffmpeg 按时间轴合成整首。
2. **画幅** —— 竖屏 9:16（抖音/视频号）、横屏 16:9（B站/YouTube）、方形 1:1。
3. **时间轴来源** —— 用户有没有 LRC？没有就自动对齐（下面第二节），并说清识别可能有偏差。

另外问一句情绪基调与偏好意象；如果涉及人物，**主动建议用背影/剪影/局部特写**——AI 生成正脸容易崩，且背影在回忆/分手这类题材里情绪更强。这是个值得给的专业意见。

## 一、先把音频摸清楚

```bash
ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1 "<audio>"
```

拿到总时长，后面每一步都要用它。

### 第零步：先查 MP3 内嵌歌词（可能直接省掉整套 ASR）

很多下载来的 mp3 在 `TEXT` / `USLT` / `SYLT` tag 里就带着**带时间戳的 LRC**，精度远高于 whisper 推算：

```bash
ffprobe -v error -show_entries format_tags -of json "<audio>"
```

查到 LRC 就直接解析用，第二节整段跳过。注意两个坑：

- **乱码修复**：常见是「UTF-8 字节被按 latin-1 逐字节存进 GBK 标签」，表现为打印出来全是 `Ã÷Ìì` 这类字符。修复：`s.encode('latin-1').decode('gbk')`。
- 内嵌 LRC 头几行往往是 `[00:01.01]歌名 - 歌手`、`词：xxx`、`曲：xxx` 这类**信息行**，做字幕时要把它们从正文歌词里剔出来（比如按 `t < 10s` 过滤），单独做成片头信息卡。

## 二、时间轴：怎么从音频推出每句歌词的时刻

### 首选：ffmpeg 的 whisper 滤镜

**不要用 `faster-whisper`**。它在 Windows + ctranslate2 + MKL 上极易在**模型加载阶段**就崩：

```
RuntimeError: mkl_malloc: failed to allocate memory
```

降线程数（`cpu_threads=1`）、关 xet、设 `MKL_THREADING_LAYER=SEQUENTIAL` **全都无效**。别在这上面浪费时间，直接走 ffmpeg。

模型用 whisper.cpp 的 ggml（`ggerganov/whisper.cpp` 仓库，`ggml-small.bin` 约 487MB）：

```bash
ffmpeg -i "<audio>" -vn \
  -af "whisper=model=<path>/ggml-small.bin:language=zh:queue=3000:destination=build/asr.srt:format=srt" \
  -f null -
```

CPU 上速度约 1.2x realtime，4 分钟的歌大概 3.5 分钟跑完。

### 关键认知：这个滤镜的时间戳是「定长分块」，不是真实词级时间

它按固定块长切音频（`queue=3000` → 实测每块 2.978s），时间戳就是块边界。所以：
- 输出的 SRT 里每条的 start 都落在 `n × 2.978s` 上，end 是假的（start+2000/3000）。
- 识别文本会有幻觉：`字幕:XXX`、`歌词制作:`、随便一个英文名，**这些一律忽略**。
- 简单/重复的段落（前奏、间奏、尾奏）几乎全是幻觉。

**但块边界 ≈ 乐句边界**，一条中文歌词通常落在 1–3 个块里。据此可以还原出精确的乐句网格。

### 用歌词原文反推网格（这一步才是重点）

不要试图逐字对齐。做的是**结构推演**：

1. 把 SRT 里**真实命中歌词**的块挑出来，当作锚点。例：
   `[29.78] 一片秋葉 輕輕落下`、`[44.67] 海留在我心里`（→ 那伤害流在我心里）、
   `[98.27] 你的思绪`（→ 还有爱你的思绪）、`[113.16] 我的情絲纏`（→ 剪不断我的情思缠绵）。
2. 假设一个**乐句网格**：前奏长度 `I`，每句时长 `B`，第 k 句起点 `S_k = I + (k-1)·B`。
3. 用锚点试算 `B`，直到所有锚点都落进对应的句子里。
4. **重复段落的推导**：这类歌基本是「前奏 → 主副歌 → 间奏 → 重复」。间奏长度通常等于前奏长度，
   于是 `第二遍起点 = 第一遍起点 + 主副歌总长`。用它去验证 SRT 里第二遍的首句锚点。
5. **验收标准：每个锚点都要对得上。** 全部吻合才继续；有一个对不上就说明网格错了。

《秋恋》实测网格（可直接当参考值）：`I = 29.78`、`B = 7.2`、第二遍起点 `145.92`、
间奏 `29.74`（≈前奏）、每 12 句一个循环。26 句里 12 处锚点全部吻合。

### 兜底

网格推不出来时：把已推出的时间轴写成 `.lrc` 交给用户校对，让他给几个"第 X 句应该在 Y 秒"的修正，
再整体平移/重算。**永远要把 lrc 一起交付**，这是最省事的返工通道。

## 三、场景画面（混合方案才需要）

1. **先出一个锚点图并让用户确认**，再用它派生其余全部。
   - 纯文生图做锚点；其余走**以锚点为参考图**的编辑/派生，不要用文字描述重新生成——一致性靠参考图，不靠文字。
   - 把风格 token（光线/色调/颗粒/景深/氛围）冻成一段固定文字，在每条派生提示词里**原样复用**，只改场景内容。
   - 每张都写 `Vertical 9:16 composition with the lower third empty and uncluttered`，给歌词留位置。
   - 明确写 `No text, no watermark, no logo`，否则画面里会出现假文字。
   - **画幅全套统一**，逐张核对实际像素尺寸。
2. 场景切分按**歌词段落**走：一个 4 句的段落配一个场景，段内可换一次。
3. 重复段落（第二遍副歌）用同一批图但**换运镜方向**，避免看起来是原样重播。
4. 集齐后拼一张 contact sheet 一次性验收，比逐张看省 context。
5. **ImageGen 的图右下角自带 "AI" 水印**：1024x1536 的图裁掉底部约 100px 即可去掉，
   然后再做 9:16 居中裁切 + Lanczos 放大到 1080x1920。
6. 提示词里写 "lower third empty and uncluttered" 有概率让模型把**下三分之一直接画成空白**，
   尤其室内场景。逐张检查 contact sheet，空白的那张用 "full-bleed composition, no blank
   margins" 重出。另外图与编号的对应关系要显式固定（按文件名时间戳排一份清单），
   否则中途补图会把整批顺序打乱。
7. 源图只有 864x1536（裁切后），**zoompan 的 z 必须始终 >= 1.0**（如 1.02→1.18），
   靠裁切做运镜，不要再放大；预放大到 1.35x 那条只适用于高分辨率源图。
8. 派生一致性：ImageGen 走 **image-to-image（image1=锚点图，input_fidelity=high）**，
   提示词开头写 "Same 35mm Kodak film photograph style as the reference image."，
   风格 token 原样复用，只改场景描述。

## 四、合成（ffmpeg）

### 4.1 运镜：zoompan 做缓慢推拉/平移

先把图预放大到 1.35x 再 zoompan，否则推上去会糊：

```
scale=1458:2592:force_original_aspect_ratio=increase,crop=1458:2592,
zoompan=z='1+0.25*on/<frames-1>':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=<frames>:s=1080x1920:fps=30
```

平移用固定 `z=1.20` + `x` 从 0 走到 `(iw-iw/zoom)`。节奏要慢——15 秒只推 25%。

### 4.2 压暗渐变：保证歌词可读

生成一张带 alpha 渐变的黑图，逐段 overlay 上去（不要用 `drawbox`，做不出渐变）：

```
ffmpeg -f lavfi -i "color=c=black:s=1080x1920" \
  -vf "format=rgba,geq=r='0':g='0':b='0':a='clip((Y-820)/1100*222,0,222)'" -frames:v 1 scrim.png
```

从 Y=820 开始渐到 0.87 不透明度。**歌词若放在 2/3 高度，压暗必须从那个高度起算**，
只压最底部是没用的。

### 4.3 字幕：ASS 逐句动画

- 字体直接写 `Microsoft YaHei`，ffmpeg 的 libass 能解析系统字体，**不需要** `fontsdir`。
- 每句一条 Dialogue，用 `\fad(380,320)` 淡入淡出 + `\move(x,y0,x,y1)` 轻微上浮。
- 显示区间：`start-0.34` 到 `min(end+0.6, 下一句start-0.1)`，否则会两句同时挂在屏幕上。
- 描边 `Outline=1` + `Shadow=3`，白字压照片更稳。
- 文件存 UTF-8 with BOM。
- 想调位置用 `\pos()`，别只靠 Style 的 MarginV——标题和副标题都居中对齐时会叠在一起。

### 4.4 交叉溶解：**按内存分组做，不要一次串 15 路输入**

```bash
ffmpeg -i a -i b -i c -i d -filter_complex \
  "[0:v][1:v]xfade=transition=fade:duration=0.8:offset=O1[x1];\
   [x1][2:v]xfade=...:offset=O2[x2];[x2][3:v]xfade=...:offset=O3[vout]" ...
```

`offset_k = sum(D_1..D_k) - k*transition`。
要让每段边界恰好落在 `E_i`，取 `D_i = (E_i - S_i) + transition`（即每段末尾多留一个转场长度），
最终总长会多出 `transition`，用 `-t` 裁回音频时长即可。

**内存纪律**（这条是踩过的坑）：15 路输入串一条 xfade 链在 16GB / 只剩 3GB 的机器上会
`Cannot allocate memory`、`x264 malloc of size N failed`。改成三级：

1. 每 3–4 段一组 → 组内 xfade → `part_k.mp4`
2. 各 part 再 xfade → `bg.mp4`（纯画面，无字幕无音轨）
3. `bg.mp4` + 音频（2 路输入）叠 ASS → 最终成片

同时全程 `-threads 2`、中间产物用 `-preset ultrafast -crf 14`。
分组不会破坏时间轴：因为组内总长 = `E_last - S_first + transition`，二级链的 offset 会自然对齐。

### 4.5 最终命令

```bash
ffmpeg -i bg.mp4 -i audio.mp3 -filter_complex \
  "[0:v]ass=build/lyrics.ass,fade=t=in:st=0:d=1.6,fade=t=out:st=<total-2.6>:d=2.6,format=yuv420p[v];\
   [1:a]afade=t=out:st=<total-3.6>:d=3.6[a]" \
  -map "[v]" -map "[a]" -c:v libx264 -preset veryfast -crf 19 -threads 3 \
  -pix_fmt yuv420p -r 30 -c:a aac -b:a 256k -ar 44100 -t <total> -movflags +faststart out.mp4
```

### 4.6 动态元素层（花瓣／尘埃／光斑）与旋转运镜

**动态层**：用 Python 逐帧画好后以 rawvideo 管道喂给 ffmpeg，存成带 alpha 的 qtrle mov：

```
ffmpeg -f rawvideo -pix_fmt rgba -s 720x1280 -r 30 -i - -c:v qtrle -pix_fmt argb fx.mov
```

- 想**无缝循环**：所有运动都写成周期函数，周期 = 循环长度 L。平移用 `sin(2π·k·t/L)`（k 取整数），
  落体用 `(y0+v·t) mod H`（v 取 `H/L` 的整数倍），自转用整圈。这样首尾帧完全接得上。
- 合成时 `-stream_loop -1 -i fx.mov`，配合 `overlay=0:0:shortest=1`（否则无限循环不结束），
  再 `scale` 到成片尺寸。720x1280 放大到 1080x1920 完全够用，生成快 3 倍。

**旋转运镜**：`zoompan` 不能旋转，要在它前面加 `rotate`，并且**必须先放大留出余量**：

```
scale=1404:2496,rotate=a='0.018*sin(2*PI*t/9)':c=black:ow=1404:oh=2496,zoompan=...
```

旋转角 α 下能被完整覆盖的居中矩形约为 `W-H·sinα` × `H-W·sinα`，zoompan 的取景窗口
（宽 `iw/zoom`）+ 平移偏移必须落在这个矩形内，否则角上会露黑边。
实操安全值：放大 1.30x、α ≤ 0.02 rad、zoompan 的 z ≥ 1.08、平移范围控制在 45~150px。

## 五、情绪设计：怎么让 MV 真的打动人

画面数量不够 → 加画面，是**错的**解法。用户说"没什么感觉/不感动"时，先按下面三条自查：

1. **光的时间错了**。治愈＝正午明亮、蓝绿通透；感动＝斜阳将尽、暗部冷蓝、亮部橙金。
   同一张图换个光，情绪完全不同。**先做一版调色对比图给用户看**（上排原版 / 下排调色），
   比空谈方向有效得多。调色参数见下。
2. **人物没有状态**。全是远景背影＝观众看到的是"漂亮的构图"，代入不了。
   感动靠"看到她在经历什么"：蹲下、低头、空着的邻座、独自奔跑、逆光闭眼的侧脸。
3. **画面和歌词没有对位**。最戳的画面必须压在最疼的那一句上。
   做法：先把歌词里**有具体动作/情绪的句子**挑出来（例：「在楼梯的角落找勇气 抖着肩膀哭泣」
   「曾经并肩往前的伙伴」「含着泪微笑」「黑暗中跌倒」），照着它们写画面提示词，
   再把这些镜头放到该句的时间段上。这一步是"感动"的主要来源。

**黄昏调色（ffmpeg，作用在画面链末尾、字幕之前）**：

```
eq=saturation=0.74:contrast=1.06:brightness=-0.035,
colorbalance=rs=-0.06:bs=0.09:rm=-0.01:bm=0.01:rh=0.07:gh=0.02:bh=-0.07,
vignette=angle=PI/5.5
```

暗部压向冷蓝、亮部拉向橙金、降饱和、加暗角。

**结尾沉淀**：最后一句唱完后往往还有 20–30s 尾巴，别让它直接淡黑。
用 `eq` 的时间表达式让画面**慢慢褪色、变冷、变暗**，配合音乐先淡出：

```
eq=saturation='max(1-0.45*(t-259.8)/12,0.55)':brightness='min(-0.16*(t-259.8)/12,0)'
```

（`eq` 的选项支持 `t`/`n` 表达式变量。）

**副歌歌词高亮**：另建一个 Style（字号更大、暖白 Primary、加粗、描边更厚），
用关键词表判定副歌行（`明天你好`/`含着泪`/`长大以后`…），命中就用高亮样式。

## 六、验收

抽 5–6 帧（标题、首句、换场、副歌、结尾）拼成一张 contact sheet 看一次，比逐帧看省得多。
检查项：中文有没有出豆腐块、标题和副标题有没有叠、歌词在**最亮的那张图**上是否仍然清楚、
场景切换点是否和段落对得上。
**字幕标签泄漏时画面上会出现 `\move(...)` 之类的原始文本**——不能看图时用像素法兜底：
统计字幕带（y≈1180–1400）里"亮且低饱和"像素的水平跨度，正常短句 300–450px，
一旦超过 700px 就是标签被当成了文字渲染。

## 环境坑（Windows）

- **ffmpeg 滤镜选项里的绝对路径会被冒号截断**：`whisper=model=C:/x/y.bin` 会报
  `No option name near '/x/y.bin'`（`:` 被当成参数分隔符）。`ass=` 滤镜同理。
  解法：要么转义成 `C\:/x/y.bin`，要么干脆 **cd 到 build 目录、全部用相对路径**（最稳）。
- bash 里**可能没有 coreutils**：`ls` / `head` / `which` / `rm` / `sleep` 全部 command not found，
  而且 `rm` 的 shim 会直接报错挂掉。**删文件、列目录一律用 Python 或 ffprobe**，别用 shell。
- Python 的 stdout 在管道里走系统编码（cp936），直接 `print()` 中文会变成乱码假象——
  **把结果写成 UTF-8 文件再 Read**，别靠看终端输出判断编码对错。
- 程序化背景（用户没要 AI 图时）用 numpy+PIL 就够：垂直渐变 + 径向暖光 + 光束/剪影/bokeh
  + 胶片颗粒 + 暗角，9 张 1458x2592 底图渲染只要几秒，成片干净且不会有人脸崩坏。
- HuggingFace 直连常被代理挡（502）。下模型必须：
  `HF_ENDPOINT=https://hf-mirror.com` + `HF_HUB_DISABLE_XET=1`（xet 通道会 401）。
- 长任务放后台跑并按段打印进度，别整条命令闷着。
- **ImageGen 千万别在同一回合并行发多个调用**：落地文件名是
  `提示词前缀_秒级时间戳.png`，同秒生成的会**互相覆盖**（5 张只剩 3 张）。
  必须**串行**生成，每张落地后立即 `os.replace` 改成唯一名再出下一张。
- 从旧脚本 copy 派生新脚本时，先检查旧脚本里是否带未修的 bug
  （本例：最终合成的音频流错写成 `[1:a]`（fx.mov 无音轨），
  正确是 `[2:a]`（MP3 输入）；Edit 修 bug 时 old/new 范围务必只圈住目标行，
  改完把整段 print 出来核对一遍）。
- **ASS 的所有 override 标签必须在同一个 `{}` 块里**：`{\fad(..)}{\kf30}字` 之后再写
  `\move(...)` 会被 libass 当成**普通文本渲染出来**（画面上直接出现 `\move(540,1294,...)`）。
  正确：`{\fad(..)\move(..)\fscx100\t(0,140,\fscx116)}{\kf30}字`。
- 逐字点亮用 `\kf`（单位厘秒）：`{\kf39}看{\kf39}昨…`，把句子时长按字数均分（尾部留 ~30% 余量）。
  未点亮的字显示 SecondaryColour，所以 **SecondaryColour 要带 alpha**（如 `&H68B8B0A8`），
  才有"从半透明灰渐变为不透明白"的浮现感。
- 只想重跑最后一步时，**别用 `split('# ---------- 3.')` 切脚本**——本例的注释块编号让 head
  里包含了全部渲染代码，结果白跑 6 分钟。直接手写一个只做最终合成的 final.py。
