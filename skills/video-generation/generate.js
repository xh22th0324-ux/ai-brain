#!/usr/bin/env node
/**
 * 图片生成视频 —— 提交 + 轮询 + 落盘一体化脚本。
 *
 * 用法:
 *   node generate.js <任务描述.json>          提交并等到生成完成（不下载）
 *   node generate.js --download <taskId> [保存目录]   把成片取回本地
 *
 * 任务描述文件（UTF-8）:
 *   {
 *     "mode": "IMAGE" | "REFERENCE",
 *     "aspectRatio": "9:16" | "16:9",
 *     "prompt": "……",
 *     "images": ["C:\\绝对路径\\1.png", "C:\\绝对路径\\2.png"],
 *     "outDir": "C:\\保存目录"        // 可省，默认任务描述文件所在目录
 *   }
 *
 * 无第三方依赖，只要有 node 和 curl.exe（Windows 10+ 自带）。
 * 进度输出到 stdout，PowerShell 会把 stderr 当错误流。
 */
const { spawn } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

// 换域名只改这一行。环境变量 VIDEO_API_BASE 可临时覆盖。
const API_BASE = process.env.VIDEO_API_BASE || "https://sage-ai.net/api/v1/video/skill";

// 本地先查一遍，省掉一次白传。服务端仍会再校验一次，以它为准。
const RULES = {
  IMAGE: { label: "图生视频", maxImages: 2, extensions: ["jpg", "jpeg", "png"] },
  REFERENCE: { label: "参考生视频", maxImages: 5, extensions: ["jpg", "jpeg", "png", "webp"] },
};

const ASPECT_RATIOS = ["9:16", "16:9"];

/** 单张图片大小上限。 */
const MAX_IMAGE_BYTES = 30 * 1024 * 1024;

/** 提示词长度上限。 */
const MAX_PROMPT_LENGTH = 20000;

const POLL_INTERVAL_MS = 5000;

// 生成中每隔这么久再报一次进度。只在状态变化时报的话，「生成中」会是一段
// 三分钟不出声的空白——用户分不清是在跑还是卡死了，而「卡死了」的第一反应
// 是重试，重试只会让队更长。
const RUNNING_TICK_MS = 30000;

// 整体超时。排队时长取决于前面有多少人，所以给得很宽。
const TOTAL_TIMEOUT_MS = 40 * 60 * 1000;

// 连续多少次轮询失败才放弃。网络抖一下不该让整个任务算失败。
const MAX_POLL_FAILURES = 5;

// ---------------------------------------------------------------- 输出

function progress(percent, text) {
  console.log("[进度 %d%%] %s", percent, text);
}

function fail(text) {
  console.log("[错误] %s", text);
  process.exit(1);
}

// ---------------------------------------------------------------- curl

/** 跑一次 curl，拿到 stdout。不用 shell，参数原样传给 curl，免去转义问题。 */
function curl(args, { binary = false } = {}) {
  return new Promise((resolve, reject) => {
    const proc = spawn("curl.exe", args, { stdio: ["ignore", "pipe", "pipe"] });
    const out = [];
    const err = [];
    proc.stdout.on("data", (d) => out.push(d));
    proc.stderr.on("data", (d) => err.push(d));
    proc.on("error", (e) => reject(new Error("起不动 curl.exe：" + e.message)));
    proc.on("close", (code) => {
      if (code !== 0) {
        reject(new Error("curl 退出码 " + code + "：" + Buffer.concat(err).toString("utf8").trim()));
        return;
      }
      resolve(binary ? Buffer.concat(out) : Buffer.concat(out).toString("utf8"));
    });
  });
}

// 调接口并解析 {code,msg,data,errorCode}。分支判断用 errorCode，别匹配 msg 文案。
async function callApi(args) {
  const text = await curl(["-sS", "--max-time", "60", ...args]);
  let body;
  try {
    body = JSON.parse(text);
  } catch (e) {
    // 网关挂了或者被拦在前面时返回的是 HTML，直接把 JSON 解析错误抛出去
    // 只会让人一头雾水，所以带上原文的开头
    throw new Error("接口返回的不是 JSON：" + text.slice(0, 200));
  }
  if (String(body.code) !== "200") {
    const e = new Error(body.msg || "接口返回失败");
    e.errorCode = body.errorCode;
    throw e;
  }
  return body.data;
}

// ---------------------------------------------------------------- 校验

function readJobFile(file) {
  let raw;
  try {
    raw = fs.readFileSync(file, "utf8");
  } catch (e) {
    fail("读不到任务描述文件 " + file + "：" + e.message);
  }
  // PowerShell 的 Out-File -Encoding utf8 会写 BOM，JSON.parse 认不了
  if (raw.charCodeAt(0) === 0xfeff) raw = raw.slice(1);
  try {
    return JSON.parse(raw);
  } catch (e) {
    fail("任务描述文件不是合法 JSON：" + e.message);
  }
}

// 本地先查一遍，省掉「传完几十 MB 才被拒」。
function validate(job) {
  const mode = job.mode || "IMAGE";
  const rule = RULES[mode];
  if (!rule) {
    fail("生成方式只能是 IMAGE（图生视频）或 REFERENCE（参考生视频），收到 " + mode);
  }

  const aspectRatio = job.aspectRatio || ASPECT_RATIOS[0];
  if (!ASPECT_RATIOS.includes(aspectRatio)) {
    fail("画面比例只能是 " + ASPECT_RATIOS.join("、") + "，收到 " + job.aspectRatio);
  }

  const prompt = (job.prompt || "").trim();
  if (!prompt) fail("缺少提示词");
  if (prompt.length > MAX_PROMPT_LENGTH) {
    fail(`提示词 ${prompt.length} 字，超过上限 ${MAX_PROMPT_LENGTH} 字`);
  }

  const images = Array.isArray(job.images) ? job.images.filter(Boolean) : [];
  if (!images.length) fail("至少要一张图片");
  if (images.length > rule.maxImages) {
    fail(`${rule.label}最多 ${rule.maxImages} 张，收到 ${images.length} 张`);
  }

  images.forEach((file, i) => {
    let stat;
    try {
      stat = fs.statSync(file);
    } catch (e) {
      fail(`第 ${i + 1} 张图片找不到：${file}`);
    }
    if (!stat.isFile()) fail(`第 ${i + 1} 张不是文件：${file}`);
    const ext = path.extname(file).replace(/^\./, "").toLowerCase();
    if (!rule.extensions.includes(ext)) {
      fail(`第 ${i + 1} 张是 .${ext}，${rule.label}只接受 `
        + rule.extensions.map((e) => "." + e).join("、"));
    }
    if (stat.size > MAX_IMAGE_BYTES) {
      fail(`第 ${i + 1} 张 ${(stat.size / 1024 / 1024).toFixed(1)}MB，`
        + `超过上限 ${MAX_IMAGE_BYTES / 1024 / 1024}MB`);
    }
  });

  return { mode, aspectRatio, prompt, images };
}

// ---------------------------------------------------------------- 主流程

/** 把成片取回本地。生成完之后单独调，用户说要才下。 */
async function download(taskId, outDir) {
  if (!/^[0-9a-f]{32}$/.test(taskId || "")) {
    fail("taskId 格式不对，应该是 32 位十六进制");
  }
  const dir = outDir || process.cwd();
  const outFile = path.join(dir, `video_${taskId}.mp4`);
  try {
    fs.mkdirSync(dir, { recursive: true });
    await curl([
      "-sS", "--max-time", "600", "-o", outFile,
      `${API_BASE}/tasks/${taskId}/download?download=1`,
    ]);
  } catch (e) {
    fail("下载失败：" + e.message);
  }
  // curl 拿到 4xx 也会把响应体写进文件，所以要验一下确实是视频。
  // 只读开头那几十个字节：视频可能几百 MB，整份读进内存会直接把 node 撑爆，
  // 而用户看到的只是脚本莫名崩掉。
  if (!fs.existsSync(outFile) || fs.statSync(outFile).size === 0) {
    fail("下载下来是空文件");
  }
  const head = Buffer.alloc(64);
  const fd = fs.openSync(outFile, "r");
  const read = fs.readSync(fd, head, 0, 64, 0);
  fs.closeSync(fd);
  if (head.slice(4, 8).toString("latin1") !== "ftyp") {
    // 不是视频时开头这段基本就是错误 JSON，够看清原因了
    const preview = head.slice(0, read).toString("utf8").replace(/\s+/g, " ").trim();
    fs.unlinkSync(outFile);
    fail("下载到的不是视频：" + preview);
  }
  console.log("===VIDEO_FILE_START===");
  console.log(JSON.stringify({ file: outFile, sizeBytes: fs.statSync(outFile).size }));
  console.log("===VIDEO_FILE_END===");
}

async function main() {
  if (process.argv[2] === "--download") {
    return download(process.argv[3], process.argv[4]);
  }

  const jobFile = process.argv[2];
  if (!jobFile) {
    console.error("用法: node generate.js <任务描述.json>");
    console.error("      node generate.js --download <taskId> [保存目录]");
    process.exit(2);
  }

  progress(0, "启动任务");

  const job = readJobFile(jobFile);
  const outDir = job.outDir || path.dirname(path.resolve(jobFile));

  progress(5, "校验中");
  const input = validate(job);

  // ⚠️ 提示词必须走文件，别改成 -F "prompt=${文本}" 那种命令行传参。
  // Windows 上 curl.exe 走 ANSI 入口，中文参数会被转成系统代码页（GBK）后原样
  // 发出，服务端按 UTF-8 解析就是乱码——而且**不报错**，片子照常生成，只是内容
  // 和描述对不上。-F "name=<文件" 把文件内容当字段值发，字节原样过去。
  const promptFile = path.join(
    fs.mkdtempSync(path.join(os.tmpdir(), "video-skill-")), "prompt.txt");
  // 不写 BOM：BOM 会变成提示词的第一个字符
  fs.writeFileSync(promptFile, input.prompt, { encoding: "utf8" });

  const form = [
    "-F", `mode=${input.mode}`,
    "-F", `aspectRatio=${input.aspectRatio}`,
    "-F", `prompt=<${promptFile}`,
  ];
  // 顺序就是使用顺序：图生视频传两张时，第一张是首帧、第二张是尾帧
  input.images.forEach((file) => {
    form.push("-F", `images=@"${file}"`);
  });

  // 清理写成函数、在两条路径上各调一次，**不能用 finally**：
  // fail() 里是 process.exit()，它不会展开调用栈，finally 根本不执行。
  // 用 finally 的话，恰恰是最常见的那条失败路径（队列满、限额用尽）每次都会
  // 在临时目录里留下一份带完整提示词的 prompt.txt。
  const cleanup = () => {
    try {
      fs.unlinkSync(promptFile);
      fs.rmdirSync(path.dirname(promptFile));
    } catch (e) {
      // 删不掉不值得让整个任务失败，系统迟早会清
    }
  };

  let task;
  try {
    task = await callApi(["--max-time", "300", "-X", "POST", `${API_BASE}/tasks`, ...form]);
  } catch (e) {
    cleanup();
    fail(e.message);
  }
  cleanup();

  progress(8, "校验合格，提交任务");

  const taskId = task.taskId;
  const startedAt = Date.now();
  let lastPercent = 8;
  let lastQueueAhead = null;
  let lastRunningTick = 0;
  let failures = 0;

  while (true) {
    if (Date.now() - startedAt > TOTAL_TIMEOUT_MS) {
      fail("等待超过 40 分钟仍未完成，已停止等待。任务可能还在后台跑");
    }
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));

    let status;
    try {
      status = await callApi([`${API_BASE}/tasks/${taskId}`]);
      failures = 0;
    } catch (e) {
      // 网络抖一下不该让整个任务算失败——片子可能已经在生成了
      if (++failures >= MAX_POLL_FAILURES) {
        fail("连续 " + failures + " 次查不到任务状态，已停止等待：" + e.message);
      }
      continue;
    }

    if (status.status === "QUEUED") {
      const ahead = status.queueAhead || 0;
      // 前面的人数一变就再报一次：只报一次的话用户会盯着不动的进度以为卡死。
      if (lastPercent !== 15 || ahead !== lastQueueAhead) {
        progress(15, ahead > 0 ? `排队中，前面还有 ${ahead} 个` : "排队中，马上轮到");
        lastPercent = 15;
        lastQueueAhead = ahead;
      }
      continue;
    }

    if (status.status === "RUNNING") {
      // 百分比固定报 35，**不要改成按真实进度报 40/55/70**：话术表是按百分比
      // 查行的，报一个表里没有的数字，照着话术表转述的那一头就没法办了。
      // 会变的信息放在后半句——用时在走，就说明它是活的。
      const now = Date.now();
      if (lastPercent !== 35 || now - lastRunningTick >= RUNNING_TICK_MS) {
        // 用服务端给的用时：它是从真正开始生成算的，比脚本从提交算起更准。
        // 拿不到就退回自己算，宁可略长也别不报。
        const used = status.elapsedSeconds != null
          ? status.elapsedSeconds
          : Math.round((now - startedAt) / 1000);
        progress(35, `生成中，已用时 ${used} 秒`);
        lastPercent = 35;
        lastRunningTick = now;
      }
      continue;
    }

    if (status.status === "SUCCESS") {
      // 生成完就停，**不自动下载**——先让用户决定要不要。
      // 要下载时用 --download 那条命令，taskId 在下面这段 JSON 里。
      progress(100, "制作完成");
      console.log("===VIDEO_RESULT_START===");
      console.log(JSON.stringify({
        taskId,
        durationSeconds: status.durationSeconds || null,
        sizeBytes: status.videoSize || null,
        outDir,
      }));
      console.log("===VIDEO_RESULT_END===");
      return;
    }

    if (status.status === "FAILED") {
      // 只转述接口给的文案，不猜原因。
      fail(status.errorMessage || "生成失败");
    }

    if (status.status === "CANCELED") {
      fail("任务已被取消");
    }
  }
}

main().catch((e) => fail(e.message));
