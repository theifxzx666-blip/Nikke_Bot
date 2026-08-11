---
name: nikke-guild-member-list
description: Maintain the NIKKE guild member list skill. Use when working on /成员, /名单, member names, QQ bindings, group cards, active members, or the SQLite members table used by guild raid commands.
---

# 成员名单

## Scope

查询当前启用成员名单，并为出刀、查刀、提醒等能力提供成员数据语义。AstrBot 主链路由 `guild_war_bot/skills/guild_war.py` 的 `GuildWarMemberListSkill` 处理。

## User Commands

- `/成员`
- `/名单`

## Runtime Path

- `guild_war_bot/core.py`
  - `list_members()`
  - `list_member_records()`
  - `find_member_by_qq()`
  - `resolve_member_name()`
  - `display_name_for_member()`
- `guild_war_bot/skills/guild_war.py`
  - `GuildWarMemberListSkill`
- 成员后台：`guild_war_bot/admin_web.py`
- 默认数据库：`data/guild_war.db`

## Data Fields

`members` 表关键字段：

- `name`：会战机器人内部成员名。
- `server_area`：区服，例如 `Q区` 或 `V区`。
- `qq`：QQ 号，用于把群发言人绑定到成员。
- `group_card`：群名片，用于提醒文本里的显示名。
- `active`：是否计入当前会战统计。

## Maintenance Rules

- 群内 `/成员` 只展示启用成员名，不暴露 QQ 号。
- 成员增删改优先走成员管理后台或导入脚本，不建议在群命令里开放随意写入。
- 如果出刀记录找不到成员，先检查 `qq` 绑定和 `group_card`，不要直接改出刀逻辑兜底。

## Verification

```powershell
Invoke-RestMethod http://127.0.0.1:8793/command -Method Post -ContentType "application/json" -Body (@{
  text = "/成员"
  sender_name = "测试成员"
  sender_qq = "10001"
  session_id = "skill-member-check"
} | ConvertTo-Json -Compress)
```

确认只返回 active 成员。
