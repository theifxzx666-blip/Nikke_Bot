# NIKKE Guild Bridge for AstrBot

这个目录是 AstrBot 插件模板，用于把 AstrBot 群命令转发到本项目的本地桥接服务。

插件结构按 AstrBot 官方插件形态组织：

- `metadata.yaml`：插件元数据，供 AstrBot 识别插件。
- `main.py`：继承 `Star`，使用 `@filter.command` 注册命令。
- `_conf_schema.json`：让 AstrBot WebUI 管理桥接地址、超时和管理员 QQ。
- `skills/`：暴露给 AstrBot Skill Manager 的插件内置 skill 说明。

## 安装位置

把整个 `astrbot_plugin_nikke_guild_bridge` 目录复制到 AstrBot 的插件目录，例如：

```text
supports/AstrBot/data/plugins/astrbot_plugin_nikke_guild_bridge/
```

然后在 AstrBot WebUI 里重载插件。

## 启动桥接服务

在本项目目录运行：

```powershell
cd F:\Codex\Nikke\Nikke_Bot
.\qq_bot\02-start-qq-bot.bat
```

插件默认访问：

```text
http://127.0.0.1:8793
```

优先在 AstrBot WebUI 的插件配置里修改：

- `bridge.bridge_url`
- `bridge.request_timeout_seconds`
- `bridge.outbox_poll_interval_seconds`
- `bridge.outbox_poll_attempts`
- `permissions.admin_qq_ids`

环境变量仍作为兜底兼容：

```powershell
$env:NIKKE_GUILD_BRIDGE_URL="http://127.0.0.1:8793"
$env:ADMIN_QQ_IDS="123456,234567"
```

## 当前支持命令

- `/帮助`
- `/菜单`
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

## 注意

- 这个插件只做转发，不直接改 SQLite。
- 管理员权限优先使用 AstrBot 插件配置 `permissions.admin_qq_ids`；环境变量 `ADMIN_QQ_IDS` 或 `NIKKE_GUILD_ADMIN_QQ_IDS` 只作为兜底。
- `/会战进度查询` 会轮询桥接服务 outbox，收到图片路径后再由 AstrBot 发图。
