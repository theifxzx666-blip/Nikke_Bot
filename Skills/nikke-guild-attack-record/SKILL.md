---
name: nikke-guild-attack-record
description: Maintain the NIKKE guild raid attack recording skill. Use when working on /出刀, /出刀 1200w, /代出刀, /改伤害, QQ-to-member resolution, damage parsing, or SQLite attack writes.
---

# 出刀记录

## Scope

记录成员当天出刀次数和可选伤害，支持管理员代记和修正伤害。AstrBot 主链路由 `guild_war_bot/skills/guild_war.py` 的 `GuildWarAttackRecordSkill` 和 `GuildWarAdminSkill` 处理。

## User Commands

成员命令：

- `/出刀`
- `/出刀 1200w`
- `/出刀 3500万`
- `/出刀 12500000`

管理员命令：

- `/代出刀 成员名`
- `/代出刀 成员名 1200w`
- `/改伤害 成员名 1200w`
- `/改伤害 成员名 1200w 第2刀`

## Runtime Path

- `guild_war_bot/core.py`
  - `parse_attack_command()`
  - `parse_damage()`
  - `resolve_member_name()`
  - `record_attack()`
  - `update_attack_damage()`
- `guild_war_bot/skills/guild_war.py`
  - `GuildWarAttackRecordSkill`
  - `GuildWarAdminSkill`
- 写入表：`attacks`
- 成员表：`members`

## Data Semantics

- 普通成员出刀时，优先用 `sender_qq` 在成员表里找绑定成员；找不到则用群名片 `sender_name`。
- 每名成员每天最多记录 `3` 刀。
- 伤害单位支持 `w`、`万`、`k`、`千` 和纯数字。
- `/改伤害` 默认修改该成员当天最后一刀；带 `第几刀` 时修改指定刀。

## Safety Rules

- 不要绕过成员存在校验；找不到成员时应提示先去成员后台添加。
- 不要让普通成员调用 `/代出刀`、`/改伤害`、`/重置今日`。
- 数据写入前确认当前 `GUILD_WAR_DB` 指向正确公会库。
- 不要把重复出刀强行覆盖为新伤害；修正伤害走 `/改伤害`。

## Verification

优先在测试库或临时 `GUILD_WAR_DB` 里验证：

```powershell
$env:GUILD_WAR_DB = "data/guild_war_skill_test.db"
Invoke-RestMethod http://127.0.0.1:8793/command -Method Post -ContentType "application/json" -Body (@{
  text = "/出刀 1200w"
  sender_name = "测试成员"
  sender_qq = "10001"
  session_id = "skill-record-check"
} | ConvertTo-Json -Compress)
```

验证后清理测试库，避免污染正式数据。
