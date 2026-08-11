---
name: nikke-guild-raid-time
description: Maintain the NIKKE guild raid schedule skill. Use when working on /会战时间, /突袭时间, /活动时间, raid start/end/settlement windows, battle-day rollover, or reminder-period logic.
---

# 会战时间

## Scope

展示当前联盟突袭时间、结算期和战斗日，并为查刀、日报、催刀提供统一切日口径。

## User Commands

- `/会战时间`
- `/突袭时间`
- `/活动时间`

## Runtime Path

- `guild_war_bot/core.py`
  - `RAID_START`
  - `RAID_END`
  - `RAID_SETTLEMENT_END`
  - `RAID_DAY_START_HOUR`
  - `MAIN_RAID_DAYS`
  - `battle_day()`
  - `raid_day_number()`
  - `is_main_raid_day()`
  - `raid_status_text()`

## Current Semantics

- 当前配置为 `2026-06-12 04:00` 开启，`2026-06-18 03:59` 结束。
- 结算期为 `2026-06-18 04:00` 到 `2026-06-20 23:59`。
- 每天 `04:00` 切换战斗日。
- 前 `2` 天为重点催刀期。

## Maintenance Rules

- 每期联盟突袭开始前，优先更新这里对应的 `core.py` 常量。
- 如果未来要支持配置文件，不要在多个函数里分散硬编码时间。
- 更新会战时间后，验证 `/会战时间`、`/催刀` 和 `/日报` 的切日口径一致。

## Verification

```powershell
Invoke-RestMethod http://127.0.0.1:8793/command -Method Post -ContentType "application/json" -Body (@{
  text = "/会战时间"
  sender_name = "测试成员"
  sender_qq = "10001"
  session_id = "skill-raid-time-check"
} | ConvertTo-Json -Compress)
```

确认回复包含开启、结束、结算和当前战斗日。
