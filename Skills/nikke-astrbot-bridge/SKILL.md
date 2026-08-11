---
name: nikke-astrbot-bridge
description: Maintain the NIKKE QQ bot AstrBot bridge skill. Use when working on AstrBot plugin command aliases, NapCat/OneBot message forwarding, local HTTP bridge POST /command, GET /outbox, async image replies, or bridge health checks.
---

# AstrBot 桥接

## Scope

维护 AstrBot 插件到本地会战服务的转发链路。桥接层只负责收消息、转命令、发回复；不要在 AstrBot 插件里重写会战业务逻辑。

## Runtime Path

AstrBot 到本项目：

- `qq_bot/astrbot_plugin_nikke_guild_bridge/main.py`
- `qq_bot/astrbot_plugin_nikke_guild_bridge/_conf_schema.json`
- `qq_bot/astrbot_plugin_nikke_guild_bridge/metadata.yaml`
- `qq_bot/astrbot_plugin_nikke_guild_bridge/skills/nikke-guild-war-service/SKILL.md`
- 默认桥接地址：`http://127.0.0.1:8793`
- 配置优先级：AstrBot WebUI 插件配置优先，环境变量 `NIKKE_GUILD_BRIDGE_URL` / `ADMIN_QQ_IDS` 作为兜底。

本地 HTTP 服务：

- `guild_war_bot/service_http.py`
- `POST /command`
- `GET /outbox?session_id=...&after=...`
- `GET /health`

技能分发：

- `guild_war_bot/skills/registry.py`
- `guild_war_bot/skills/guild_war.py`
- `guild_war_bot/skills/game_progress.py`
- 未命中正式 skill 时才回退 `GuildWarBot.handle_message()`

## Supported Aliases

AstrBot 插件当前监听主命令 `查刀`，并注册以下 alias：

- `进度`
- `统计`
- `出刀`
- `提醒未出刀`
- `提醒`
- `催刀`
- `日报`
- `伤害榜`
- `伤害概览`
- `会战时间`
- `会战进度查询`
- `会战进度`
- `联盟突袭进度查询`
- `成员`
- `重置今日`
- `代出刀`
- `改伤害`

## Message Flow

1. 群成员发送命令。
2. AstrBot 插件读取 `event.message_str`。
3. 插件 POST 到 `/command`，携带 `text`、`sender_name`、`sender_qq`、`session_id`。
4. 桥接服务先交给 `SkillRegistry`。
5. 如果正式 skill 未处理，再交给 `GuildWarBot.handle_message()`。
6. 同步回复直接返回 `reply`。
7. 异步图片或后续文本写入 outbox，由插件轮询后发送。

## Maintenance Rules

- 新增群命令时，先确认是正式 `guild_war_bot/skills/` 还是 `GuildWarBot.handle_message()` 分支，再同步 AstrBot alias。
- 插件结构保持 AstrBot 官方形态：`metadata.yaml`、`main.py`、`_conf_schema.json`、可选 `skills/`；不要新增平行配置系统。
- 本地 AstrBot v4.26 已将 `register_star` 标记为废弃；插件类继承 `Star`，用 `metadata.yaml` 和 `@filter.command` 完成加载与命令注册。
- 不要让同一个 NapCat 账号同时上报到旧 OneBot HTTP 机器人和 AstrBot 主链路，避免双回复。
- 管理员鉴权由 AstrBot 插件根据 `permissions.admin_qq_ids` 生成 `is_admin`，并由桥接 payload 传入；环境变量 `ADMIN_QQ_IDS` 或 `NIKKE_GUILD_ADMIN_QQ_IDS` 只作为兜底，不要把管理员 QQ 写死进插件代码。
- 桥接健康不等于 QQ 端成功；最终验收要看到群内真实回复。

## Verification

本地桥接健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8793/health
```

命令转发检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8793/command -Method Post -ContentType "application/json" -Body (@{
  text = "/查刀"
  sender_name = "测试成员"
  sender_qq = "10001"
  session_id = "skill-bridge-check"
} | ConvertTo-Json -Compress)
```

QQ群验收顺序：NapCat 在线 -> AstrBot 连接 -> 插件加载 -> 命令命中 -> 群内可见回复。
