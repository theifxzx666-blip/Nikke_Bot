# NIKKE Bot Skills

本目录整理当前 Q 群机器人已有能力，作为后续维护、扩展和迁移到正式 skill 框架时的入口索引。

这些 skill 说明的是现有能力边界和维护入口。当前 AstrBot 主链路会先进入 `guild_war_bot/skills/` 的 `SkillRegistry`；`/会战进度查询` 仍是独立截图 skill，其余会战文本命令由 `guild_war_bot/skills/guild_war.py` 统一调用 `GuildWarBot` 的业务方法。

## 技能索引

| Skill | 群命令 | 当前实现入口 |
| --- | --- | --- |
| `nikke-bot-help-menu` | `/帮助`、`/菜单`、`/指令`、`help` | `guild_war_bot/skills/guild_war.py::GuildWarHelpSkill` |
| `nikke-guild-attack-status` | `/查刀`、`/进度`、`/统计`、`/查刀 成员名` | `GuildWarAttackStatusSkill` |
| `nikke-guild-attack-record` | `/出刀`、`/出刀 1200w`、`/代出刀`、`/改伤害` | `GuildWarAttackRecordSkill`、`GuildWarAdminSkill` |
| `nikke-guild-reminder` | `/提醒未出刀`、`/提醒`、`/催刀`、`/催0刀` | `GuildWarReminderSkill` |
| `nikke-guild-daily-report` | `/日报`、`/结算` | `GuildWarDailyReportSkill` |
| `nikke-guild-damage-report` | `/伤害榜`、`/伤害概览`、`/排行` | `GuildWarDamageReportSkill` |
| `nikke-guild-member-list` | `/成员`、`/名单` | `GuildWarMemberListSkill` |
| `nikke-guild-raid-time` | `/会战时间`、`/突袭时间`、`/活动时间` | `GuildWarRaidTimeSkill` |
| `nikke-guild-progress-capture` | `/会战进度查询`、`/会战进度`、`/联盟突袭进度查询` | `guild_war_bot/skills/game_progress.py` |
| `nikke-astrbot-bridge` | AstrBot 插件命令转发、outbox 图片回传 | `qq_bot/astrbot_plugin_nikke_guild_bridge/main.py`、`guild_war_bot/service_http.py` |

## 维护顺序

1. 先确认命令入口在 AstrBot alias 和 `guild_war_bot/skills/registry.py` 哪一层。
2. 文本类会战命令放在 `guild_war_bot/skills/guild_war.py`，长耗时、截图、外部查询类能力独立成新的 skill 文件。
3. 新增命令时同步更新对应 `SKILL.md`、本索引、群内 `/帮助`、AstrBot 插件 alias 和 `qq_bot/README.md`。
4. 涉及 SQLite 写入时确认 `GUILD_WAR_DB`，避免把测试数据写进正式库。
5. 群内验收以真实 QQ 回复为准；本地端口健康只能说明链路的一部分可用。

## 已知边界

- AstrBot 插件只做桥接，不重写会战业务逻辑；管理员权限优先通过 AstrBot 插件配置 `permissions.admin_qq_ids` 传给桥接服务，环境变量 `ADMIN_QQ_IDS` 或 `NIKKE_GUILD_ADMIN_QQ_IDS` 只作为兜底。
- AstrBot 插件目录同时提供 `skills/nikke-guild-war-service/SKILL.md`，供 AstrBot Skill Manager 识别这组会战服务说明。
- 旧 OneBot HTTP 入口只作为回退，不应和 AstrBot 主链路同时接同一群消息。
- `/会战进度查询` 会控制可见游戏窗口并异步发图，必须保留单任务锁；页面识别优先复用 `data/templates/maa_nikke/` 中从 NIKKE MAA 复制来的模板资源。
- `.bat` 启动入口保持 ASCII-only；中文菜单和说明放在 PowerShell 或 Markdown 文件。
