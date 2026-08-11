# Bot Skill Framework

技能用于承载 OneBot 入口之外的独立指令能力。新增技能时优先放在本目录，避免把
`onebot_http.py` 写成一串 `if command == ...`。

## 文件职责

- `base.py`: 定义 `IncomingMessage`、`SkillContext`、`ReplyPort`、`BotSkill`。
- `registry.py`: 注册技能并按顺序分发。
- `guild_war.py`: `/帮助`、`/查刀`、`/出刀`、`/提醒未出刀`、`/日报`、`/伤害榜`、`/成员`、`/会战时间` 和管理员维护命令。
- `game_progress.py`: `/会战进度查询`，负责进入 NIKKE 截图并回图；底层 `game_progress_query.py` 会优先使用 `data/templates/maa_nikke/` 中的 NIKKE MAA 模板识别联盟入口和联盟突袭入口。

## 新增技能

1. 新建 `xxx_skill.py`。
2. 实现 `name`、`commands`、`matches()`、`handle()`。
3. 在 `registry.py` 的 `default_registry()` 里加入技能实例。
4. 如果技能会卡住消息线程，例如游戏自动化、网络抓取、图片生成，用后台线程执行，
   并先返回一句“已收到，正在处理”。

## 技能边界

- OneBot 入口只负责解析事件和发送消息。
- 技能负责判断命令、执行任务、组织回复。
- `GuildWarBot` 保留数据库和业务方法；群命令默认通过 `SkillRegistry` 调用这些方法。
- `GuildWarBot.handle_message()` 作为本地 CLI 和旧入口兼容层保留，不再是 AstrBot 主链路的第一处理面。
