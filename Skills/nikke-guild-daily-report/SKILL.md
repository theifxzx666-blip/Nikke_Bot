---
name: nikke-guild-daily-report
description: Maintain the NIKKE guild raid daily report skill. Use when working on /日报, /结算, daily attack completion reports, total damage summaries, or end-of-day guild raid text reports.
---

# 会战日报

## Scope

生成当天会战出刀和伤害日报，用于管理员查看当天收口情况。AstrBot 主链路由 `guild_war_bot/skills/guild_war.py` 的 `GuildWarDailyReportSkill` 处理。

## User Commands

- `/日报`
- `/结算`

## Runtime Path

- `guild_war_bot/core.py`
  - `daily_report()`
  - `summary()`
  - `statuses()`
  - `format_damage()`
- `guild_war_bot/skills/guild_war.py`
  - `GuildWarDailyReportSkill`

## Behavior

日报由三段组成：

- 当天总进度和未出满成员。
- 当天总伤害。
- 每个成员的 `出刀数/3` 和累计伤害。

战斗日仍按每日 `04:00` 切换。

## Maintenance Rules

- 日报是文本收口，不负责修改数据。
- 如果需要导出 CSV、图片或更复杂排行，新增独立能力，不要把 `daily_report()` 写得过长。
- 群内日报尽量保持短文本；超过平台长度限制时再考虑分页或图片化。

## Verification

```powershell
Invoke-RestMethod http://127.0.0.1:8793/command -Method Post -ContentType "application/json" -Body (@{
  text = "/日报"
  sender_name = "管理员"
  sender_qq = "10001"
  is_admin = $true
  session_id = "skill-daily-report-check"
} | ConvertTo-Json -Compress)
```

确认返回包含总进度、总伤害和成员明细。
