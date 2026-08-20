# NIKKE QQ Bot

本目录是 Q 群机器人独立工作区，日常入口用 `start-nikke-qq-bot-menu.bat`。
需要图形化管理时双击 `manager\start-manager.bat`，可在同一窗口管理服务、技能、监控和配置。
AstrBot、NapCat 和 AstrBot Python 运行环境集中放在 `supports/` 下，方便后续整体管理。

先看这三份：

- `AGENTS.md`：目录边界、端口、启动入口和维护约束
- `qq_bot/README.md`：NapCat + AstrBot + 本地桥接的部署步骤
- `supports/README.md`：AstrBot、NapCat 和本地运行依赖的位置说明
- `manager/README.md`：Windows 图形管理客户端的启动、调试和打包说明

当前主链路是：

```text
NapCat -> AstrBot (6199/ws) -> 本地桥接服务 (8793) -> GuildWarBot
```

LLM 使用本机 Ollama。AstrBot 启动脚本会按需拉起本地文本代理，不要把旧 `onebot_http.py` 当主线。
会战指令已经合并进 `guild_war_bot/skills/` 的统一 skill 分发层，后续新增群命令优先加 skill。
