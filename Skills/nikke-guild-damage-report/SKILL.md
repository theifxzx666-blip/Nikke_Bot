---
name: nikke-guild-damage-report
description: Maintain the NIKKE guild raid damage report skill. Use when working on /伤害榜, /伤害, /伤害统计, /排行, /伤害概览, /伤害汇总, damage ranking tables, averages, totals, or top-damage summaries.
---

# 伤害统计

## Scope

查询当天会战伤害排行和伤害概览。AstrBot 主链路由 `guild_war_bot/skills/guild_war.py` 的 `GuildWarDamageReportSkill` 处理。

## User Commands

排行类：

- `/伤害榜`
- `/伤害`
- `/伤害统计`
- `/排行`

概览类：

- `/伤害概览`
- `/伤害汇总`

## Runtime Path

- `guild_war_bot/core.py`
  - `damage_ranking()`
  - `damage_summary()`
  - `damage_table_rows()`
  - `format_damage()`
- `guild_war_bot/skills/guild_war.py`
  - `GuildWarDamageReportSkill`

## Behavior

- `/伤害榜` 输出每个成员三刀伤害、总伤害、占比和备注，并按总伤害降序排列。
- `/伤害概览` 输出总伤害、已出刀数、均伤、有伤害记录成员数和当前最高伤害成员。
- 未记录伤害的刀按 `0` 计入表格。

## Maintenance Rules

- 不要把“已出刀”与“已记录伤害”混为一谈；有刀但无伤害时仍应算出刀，伤害为 `0`。
- 调整伤害格式时同步检查 `parse_damage()` 与 `format_damage()`。
- 如果后续需要跨天排行，应新增日期参数解析，不要破坏默认当天查询。

## Verification

```powershell
Invoke-RestMethod http://127.0.0.1:8793/command -Method Post -ContentType "application/json" -Body (@{
  text = "/伤害榜"
  sender_name = "测试成员"
  sender_qq = "10001"
  session_id = "skill-damage-check"
} | ConvertTo-Json -Compress)
```

再验证 `/伤害概览`，确认总伤害与排行表一致。
