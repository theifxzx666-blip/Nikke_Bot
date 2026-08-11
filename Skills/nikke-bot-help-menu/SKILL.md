---
name: nikke-bot-help-menu
description: Maintain the NIKKE QQ guild bot help/menu command skill. Use when updating /帮助, /菜单, /指令, help output, documenting supported commands, or keeping AstrBot bridge aliases aligned with GuildWarBot command coverage.
---

# NIKKE 指令菜单

## Scope

维护机器人在群内展示的帮助菜单和命令总览。这个 skill 是清单入口，不承载业务逻辑；业务命令仍按各自 skill 或 `GuildWarBot.handle_message()` 分支维护。

## User Commands

- `/帮助`
- `/菜单`
- `/指令`
- `help`

## Runtime Path

- 群消息先经 AstrBot 插件 `qq_bot/astrbot_plugin_nikke_guild_bridge/main.py` 转发。
- 本地桥接服务入口是 `guild_war_bot/service_http.py` 的 `handle_bridge_command()`。
- 文本命令最终落到 `guild_war_bot/core.py` 的 `GuildWarBot.handle_message()`。
- 帮助正文由 `guild_war_bot/core.py` 的 `help_text()` 返回。

## Current Menu Coverage

成员可用命令：

- `/帮助`
- `/查刀`
- `/查刀 成员名`
- `/伤害榜`
- `/伤害概览`
- `/会战进度查询`
- `/会战时间`
- `/出刀`
- `/出刀 1200w`
- `/成员`

管理员可用命令：

- `/催刀`
- `/提醒未出刀`
- `/日报`
- `/重置今日`
- `/代出刀 成员名 1200w`
- `/改伤害 成员名 1200w [第几刀]`

## Maintenance Rules

- 新增群命令时，同步检查 `help_text()`、AstrBot 插件 alias、`qq_bot/README.md` 和本目录 `Skills/README.md`。
- 如果命令是长耗时任务，优先放入 `guild_war_bot/skills/` 的正式 skill 框架，并让帮助菜单说明它会异步返回。
- 帮助菜单面向群成员，保持短句；不要把部署步骤、端口和内部路径塞进群回复。

## Verification

从项目根目录运行桥接服务后，用 HTTP 验证：

```powershell
Invoke-RestMethod http://127.0.0.1:8793/command -Method Post -ContentType "application/json" -Body (@{
  text = "/帮助"
  sender_name = "测试成员"
  sender_qq = "10001"
  session_id = "skill-help-check"
} | ConvertTo-Json -Compress)
```

确认返回 `handled=true`，且 `reply` 包含当前命令清单。
