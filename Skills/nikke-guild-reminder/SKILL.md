---
name: nikke-guild-reminder
description: Maintain the NIKKE guild raid reminder skill. Use when working on /提醒未出刀, /提醒, /催刀, /催0刀, unfinished member mentions, zero-attack reminders, cooldown or admin-only reminder behavior.
---

# 会战提醒

## Scope

生成未出满成员提醒和 0 刀成员催刀文本。AstrBot 主链路由 `guild_war_bot/skills/guild_war.py` 的 `GuildWarReminderSkill` 处理，提醒文本不主动定时发送。

## User Commands

- `/提醒未出刀`
- `/提醒`
- `/未出刀`
- `/催刀`
- `/催一下`
- `/催0刀`

## Runtime Path

- `guild_war_bot/core.py`
  - `remind_text()`
  - `urge_zero_attack_text()`
  - `display_name_for_member()`
  - `is_main_raid_day()`
  - `raid_status_text()`
- `guild_war_bot/skills/guild_war.py`
  - `GuildWarReminderSkill`

## Behavior

- `/提醒未出刀` 列出所有未出满成员，并显示剩余刀数。
- `/催刀` 只提醒当天 `0/3` 刀成员。
- `/催刀` 只在重点催刀期直接生成 0 刀提醒；非重点期会提示当前会战状态并建议改用 `/提醒未出刀`。
- 提醒名称优先使用成员表里的 `group_card`，没有则回退成员名。

## Safety Rules

- 默认被动回复，不做自动刷屏。
- 如果新增主动提醒，必须加管理员开关、冷却和人工确认。
- 不要在 AstrBot 插件里直接群发多个提醒；统一通过桥接服务和业务层生成文本。
- 群 at 语法由平台层决定；当前文本只生成 `@群名片` 风格内容。

## Verification

```powershell
Invoke-RestMethod http://127.0.0.1:8793/command -Method Post -ContentType "application/json" -Body (@{
  text = "/提醒未出刀"
  sender_name = "管理员"
  sender_qq = "10001"
  is_admin = $true
  session_id = "skill-reminder-check"
} | ConvertTo-Json -Compress)
```

确认输出包含未出满成员和剩余刀数。
