---
name: nikke-guild-attack-status
description: Maintain the NIKKE guild raid attack status query skill. Use when working on /查刀, /查刀 成员名, /进度, /统计, member daily status reports, remaining attack counts, or SQLite-backed progress summaries.
---

# 会战查刀

## Scope

查询当天联盟突袭出刀进度、未出满成员和单个成员明细。AstrBot 主链路由 `guild_war_bot/skills/guild_war.py` 的 `GuildWarAttackStatusSkill` 处理，并复用 `GuildWarBot` 的业务方法。

## User Commands

- `/查刀`
- `/进度`
- `/统计`
- `/查刀 成员名`
- `/查询 成员名`
- `/查成员 成员名`

## Runtime Path

- `guild_war_bot/core.py`
  - `summary()`
  - `member_report()`
  - `statuses()`
  - `battle_day()`
- `guild_war_bot/skills/guild_war.py`
  - `GuildWarAttackStatusSkill`
- 数据库默认路径：`data/guild_war.db`
- 可用环境变量覆盖：`GUILD_WAR_DB`

## Data Semantics

- 每名成员每日最多 `3` 刀，常量为 `MAX_ATTACKS_PER_MEMBER`。
- 战斗日按每日 `04:00` 切日，`04:00` 前算前一天。
- `/查刀` 输出总出刀数、总需求刀数、出满人数和未出满名单。
- `/查刀 成员名` 输出该成员当天刀数、剩余刀数、总伤害和明细时间。

## Maintenance Rules

- 不要在 AstrBot 插件里重新计算进度；插件只转发命令。
- 调整切日、最大刀数、成员过滤时，优先改 `guild_war_bot/core.py` 的常量和查询函数。
- 成员找不到时，提示去成员管理后台确认名称，不要自动创建成员。
- 调整 skill 匹配规则时保持外部命令和回复口径兼容。

## Verification

```powershell
Invoke-RestMethod http://127.0.0.1:8793/command -Method Post -ContentType "application/json" -Body (@{
  text = "/查刀"
  sender_name = "测试成员"
  sender_qq = "10001"
  session_id = "skill-status-check"
} | ConvertTo-Json -Compress)
```

再用一个真实成员名验证 `/查刀 成员名`。
