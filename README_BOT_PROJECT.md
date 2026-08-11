# NIKKE QQ Bot 独立工作区

本目录是 Q 群机器人独立管理目录。日常入口：

```powershell
F:\Codex\Nikke\Nikke_Bot\start-nikke-qq-bot-menu.bat
```

## 当前主链路

```text
NapCat -> AstrBot (6199/ws) -> 本地桥接服务 (8793) -> GuildWarBot
```

LLM 使用本机 Ollama；AstrBot 通过本地文本代理访问 Ollama。旧 `onebot_http.py` 只作为回退对照，不作为主线。
会战群命令统一先进入 `guild_war_bot/skills/` 的 `SkillRegistry`；文本类命令在 `guild_war_bot/skills/guild_war.py`，截图类命令在 `guild_war_bot/skills/game_progress.py`。
AstrBot 插件按官方结构维护：`metadata.yaml` + `main.py` + `_conf_schema.json` + 可选 `skills/`。桥接地址和管理员 QQ 优先在 AstrBot WebUI 的插件配置里管理。

## 常用入口

| 项 | 入口 |
| --- | --- |
| 日常总入口 | `start-nikke-qq-bot-menu.bat`（双击） |
| 一键启动（后台） | `launcher\start.bat` |
| 一键停止 | `launcher\stop.bat` |
| 一键重启 | `launcher\restart.bat` |
| 健康检查 | `launcher\status.bat` |
| 后台页面 | `launcher\admin.bat` |
| 集中日志 | `launcher\logs.bat` → `data\logs\` |
| 交互控制台 | `launcher\menu.bat` |

> launcher 后台模式：服务窗口隐藏，输出进 `data/logs/`；NapCat 因需 QQ 扫码登录保持可见窗口。旧 `qq_bot\NIKKE_QQ_BOT_MENU.ps1` 菜单保留作兼容。

## 常用地址

| 项 | 地址 |
| --- | --- |
| AstrBot WebUI | `http://127.0.0.1:6185` |
| NapCat WebUI | `http://127.0.0.1:6099` |
| OneBot reverse WS | `ws://127.0.0.1:6199/ws` |
| 会战桥接健康页 | `http://127.0.0.1:8793/health` |
| 成员后台 | `http://127.0.0.1:8788` |
| Ollama | `http://127.0.0.1:11434` |
| AstrBot 文本代理 | `http://127.0.0.1:11435/v1` |

## 目录结构

| 路径 | 用途 |
| --- | --- |
| `start-nikke-qq-bot-menu.bat` | 根目录启动入口，双击进入中文菜单（优先 launcher） |
| `launcher/` | 统一启动器：一键启动/停止/重启/状态/后台/日志 |
| `qq_bot/` | QQ/AstrBot 启动菜单、桥接插件模板、安装脚本 |
| `guild_war_bot/` | 会战机器人业务逻辑、成员库、skills |
| `Skills/` | 机器人能力说明和后续维护 skill |
| `data/` | 会战 SQLite、配置、OCR tessdata、轻量模板、集中日志 |
| `supports/AstrBot/` | AstrBot 配置、插件数据、Ollama 文本代理、启动脚本 |
| `supports/NapCat.Shell.Windows.OneKey/` | NapCat/QQ 本地运行依赖 |
| `supports/astrbot-uv-env/` | AstrBot Python 运行环境副本 |
| `.venv/` | 会战桥接和成员后台的本地 Python 依赖 |
| `tests/` | 桥接与会战逻辑测试 |

## 文档入口

- `AGENTS.md`：后续 agent 优先看的当前事实、边界和排障顺序。
- `qq_bot/README.md`：部署拓扑、NapCat/AstrBot 配置和插件桥接步骤。
- `supports/README.md`：运行时依赖的位置说明。
