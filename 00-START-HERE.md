# 先读我（30 秒）

这是一份**个人上下文包**。你（AI）拿到它之后，按下面做就行。

## 只需要读 2 个文件

1. **`AGENTS.md`** — 入口：任务路由表 + 技能调用约定 + 随包工具 + 写作规范
2. **`context/PROFILE.md`** — 作者的背景与沟通偏好

读完这两个，再按任务去 `manifest.json` 里查具体技能。

## 不要做的事

- **不要通读全部文件**（150+ 个），会占光上下文窗口。按需检索
- 不要遍历 `skills/*/references/`，只在 `SKILL.md` 明确引用时再读那一个
- `context/ideas/` 与 `context/decisions/` 里以 `_` 开头的文件是模板，不是正文

## 要找什么，去哪找

| 想知道 | 看哪 |
|---|---|
| 作者有哪些可复用能力 | `manifest.json` → `skills[]` |
| 某个技能具体怎么做 | `skills/<name>/SKILL.md` |
| 作者过去的判断与取舍 | `context/decisions/` |
| 作者怎么表达、偏好什么 | `context/PROFILE.md` |
| 有哪些想法还没落地 | `context/ideas/`（看 `status: draft`） |
| 有现成小工具可用的动作 | `manifest.json` → `tools[]`，说明见 `tools/README.md` |

## 尖括号有两种，别搞混

| 类型 | 例子 | 正确做法 |
|---|---|---|
| **脱敏占位符** | `<PRIVATE_IP>`、`<USER_NAME>`、`<EMAIL>`、`<PASSWORD>`、`<USER_HOME>`、`<AGENT_HOME>`、`<REDACTED>` | 真实值被刻意抹掉了。**不要猜、不要编默认值**，直接向作者索取 |
| **模板参数** | `<SKILL_DIR>`、`<TITLE_ID>`、`<TID>`、`<NAME>`、`<LABEL>` | 是命令/路径模板里的变量。按当前上下文自己替换（如 `<TITLE_ID>` 换成具体游戏的 title id），拿不到具体值再问 |

分不清时按这个判据：**名字是"敏感概念"（IP/密码/姓名/路径）→ 脱敏；名字是"业务变量"（ID/目录/名字槽）→ 模板。**

## 脱敏声明

文中出现的 `<PRIVATE_IP>`、`<USER_HOME>`、`<AGENT_HOME>`、`<EMAIL>`、`<PASSWORD>`、
`<USER_NAME>`、`<REDACTED>` 都是**占位符**，真实值不在包内。需要时请直接向作者索取，
**不要猜、不要编默认值**。

---

# Read me first (English, for non-Chinese models)

This is a personal cross-model context pack. Read `AGENTS.md` then `context/PROFILE.md`.
Do **not** read all files — use `manifest.json` to locate the one skill you need.
Tokens like `<PRIVATE_IP>` / `<USER_HOME>` are redaction placeholders; ask the author
for real values instead of guessing. Note there are **two kinds** of angle brackets:
redaction placeholders (`<PRIVATE_IP>`, `<PASSWORD>`, `<USER_NAME>`) must be asked for,
while template variables (`<SKILL_DIR>`, `<TITLE_ID>`, `<NAME>`) should be filled in
from context by yourself.
