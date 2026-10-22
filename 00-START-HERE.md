# 先读我（30 秒）

这是一份**个人上下文包**。你（AI）拿到它之后，按下面做就行。

## 只需要读 2 个文件

1. **`AGENTS.md`** — 入口：任务路由表 + 技能调用约定 + 写作规范
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

## 脱敏声明

文中出现的 `<PRIVATE_IP>`、`<USER_HOME>`、`<EMAIL>`、`<PASSWORD>`、`<USER_NAME>`
都是**占位符**，真实值不在包内。需要时请直接向作者索取，**不要猜、不要编默认值**。

---

# Read me first (English, for non-Chinese models)

This is a personal cross-model context pack. Read `AGENTS.md` then `context/PROFILE.md`.
Do **not** read all files — use `manifest.json` to locate the one skill you need.
Tokens like `<PRIVATE_IP>` / `<USER_HOME>` are redaction placeholders; ask the author
for real values instead of guessing.
