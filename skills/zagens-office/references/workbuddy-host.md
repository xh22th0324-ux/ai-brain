# WorkBuddy 宿主（Windows）

本文件只补 **Windows 安装** 与 **沙箱白名单**。出件命令、schema、PPT/XLSX 纪律仍以 `SKILL.md` 为准。

## 不要跑 `integrate`

本包从 WorkBuddy 技能市场上架。`zagens-office integrate` 会把 `~\.workbuddy\skills\zagens-office\` **整目录覆盖**成通用 Hub，丢掉本包的 frontmatter 与沙箱脚本。安装引擎时只做手册 **§1–§3**（下载、校验、`--version`），然后跑下面的沙箱脚本。

## 探测

| Shell | 命令 |
|-------|------|
| PowerShell | `& "$env:USERPROFILE\.zagens-pro\bin\zagens-office.exe" --version` |
| Git Bash | `"$HOME/.zagens-pro/bin/zagens-office.exe" --version` |
| PATH 已含 bin | `zagens-office --version` |

以 stdout 版本号为准。Bash **不要**写 `%USERPROFILE%`。

当前发行以 **Windows x64** 为主。非 Windows 先告知用户，不要继续装。

## 安装引擎（未探测到时）

按官方手册执行，**不要把哈希抄进对话当记忆**（以手册当场数字为准）：

- 主：https://zagens.com/download/install.md
- 备：https://raw.githubusercontent.com/didclawapp-ai/zagens-office/main/install.md

必须同时装 **CLI + GUI** 到 `~/.zagens-pro/bin/`。校验失败的文件立刻删掉，不要运行。

## 沙箱白名单

WorkBuddy 默认沙箱写不了 `~/.zagens-pro`。出件前在本技能目录执行一次：

```text
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/ensure-workbuddy-sandbox.ps1
```

脚本行为（与 CLI `integrate` 的 WorkBuddy 分支同一约定）：

- 目标文件：`~\.workbuddy\settings.json`
- 写入项：`sandbox.extraAllowWrite` 增加 `~/.zagens-pro`（已有则跳过）
- 改前备份：`settings.json.bak-zagens-<unix>`
- 写回 UTF-8 **无 BOM**，只动这一个字段
- 没有 `settings.json`：跳过并提示用户先打开过 WorkBuddy；exit 0

stdout 一行 JSON：`ok` / `status`（`added` | `already` | `skipped` | `error`）/ `path` / `message`。

不要手改 JSON，不要重排用户其它设置项以外的内容（脚本用 JSON 解析后 pretty-print，其它键原样保留）。

## 授权

评估期约 90 天。`write`/`edit` 返回 `license_locked` 时：

1. `zagens-office license contact`（展示 `banner_markdown` / `activate_url`）
2. 用户发回授权码后 `zagens-office license activate --key <授权码>`

`read` / `schema` / `license` / `update` 不锁。
