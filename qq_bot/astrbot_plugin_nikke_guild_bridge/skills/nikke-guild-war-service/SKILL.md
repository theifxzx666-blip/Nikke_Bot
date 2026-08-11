---
name: nikke-guild-war-service
description: Use when the user asks the NIKKE QQ bot to query guild-war attack status, record attacks, remind zero-attack members, produce daily/damage reports, query raid time, or run the local progress capture command.
---

# NIKKE 会战指令服务

## Scope

本 skill 描述 AstrBot 插件可调用的 NIKKE 会战指令服务。AstrBot 插件只负责命令入口和消息转发，业务逻辑在本地 `guild_war_bot/skills/` 与 `GuildWarBot` 中执行。

## Commands

- `/帮助`、`/菜单`、`/指令`
- `/查刀`
- `/查刀 成员名`
- `/出刀`
- `/出刀 1200w`
- `/提醒未出刀`
- `/催刀`
- `/日报`
- `/伤害榜`
- `/伤害概览`
- `/会战时间`
- `/成员`
- `/会战进度查询`

管理员命令：

- `/重置今日`
- `/代出刀 成员名 [伤害]`
- `/改伤害 成员名 1200w [第几刀]`

## Runtime

消息路径：

1. AstrBot 收到群命令。
2. `astrbot_plugin_nikke_guild_bridge/main.py` 转发到本地桥接服务。
3. `guild_war_bot/service_http.py` 调用 `guild_war_bot/skills/registry.py`。
4. 对应 skill 返回文本，或将图片/后续文本写入 outbox。

默认桥接地址：

```text
http://127.0.0.1:8793
```

## Maintenance

- 新增命令时，先在 `guild_war_bot/skills/` 增加或调整正式 skill。
- 然后在 AstrBot 插件的 `COMMAND_ALIASES` 中补命令入口。
- 不要把 SQLite 写入逻辑或游戏截图逻辑重写进 AstrBot 插件。
- 管理员 QQ 在 AstrBot 插件配置 `_conf_schema.json` 的 `permissions.admin_qq_ids` 中维护。
