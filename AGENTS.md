# NIKKE QQ Bot Agent 说明

本目录 `F:\Codex\Nikke\Nikke_Bot` 是 Q 群机器人独立工作区。后续机器人部署、启动菜单、AstrBot/NapCat 接入、本地模型、会战桥接和成员后台，都优先在本目录维护；不要回写到 `F:\Codex\Nikke\Nikke` 的历史混合工作区。

## 当前主链路

已收敛为本机免费部署方案：

```text
QQ 小号
  -> NapCat
  -> AstrBot OneBot v11 反向 WebSocket
  -> AstrBot 插件 astrbot_plugin_nikke_guild_bridge
  -> 本地 HTTP 桥接服务 guild_war_bot.service_http
  -> GuildWarBot / skills / SQLite
```

不要把旧 `python -m guild_war_bot.onebot_http` 当主链路。旧 OneBot HTTP 直连只保留在 `qq_bot/legacy_onebot/` 作回退对照；同一个 NapCat 账号不要同时上报到 AstrBot 和旧 HTTP 入口，避免双回复。

## 核对过的本机状态

- AstrBot WebUI：`http://127.0.0.1:6185`
- NapCat WebUI：`http://127.0.0.1:6099`
- OneBot reverse WS：`ws://127.0.0.1:6199/ws`
- 会战桥接健康页：`http://127.0.0.1:8793/health`
- 成员后台：`http://127.0.0.1:8788`
- Ollama 原生接口：`http://127.0.0.1:11434`
- AstrBot 文本代理：`http://127.0.0.1:11435/v1`
- 当前实际拉取的本机模型：`qwen3.5:2b`

说明：旧对话/旧记忆里出现过 `qwen2.5:3b-instruct`，但本轮用 Ollama live check 核到的本机模型是 `qwen3.5:2b`。后续改 AstrBot 模型配置前，先重新查 `http://127.0.0.1:11434/api/tags`，不要直接套旧模型名。

## 主要入口

- `start-nikke-qq-bot-menu.bat`：根目录日常入口，双击进入中文菜单。优先走 `launcher\menu.bat`，不存在时回退旧菜单 `qq_bot\NIKKE_QQ_BOT_MENU.bat`。
- `launcher/`：统一启动器。`menu.bat` 交互控制台；`start.bat`（后台隐藏窗口）/`start.bat fg`（前台调试）/`stop.bat`/`restart.bat`/`status.bat`/`admin.bat`/`logs.bat`；核心脚本 `nikke_ctl.ps1`（start/stop/restart/status/logs/admin/menu 子命令）。详情见 `launcher/README.md`。
- `manager/start-manager.bat`：Windows 图形管理客户端入口；默认使用 pywebview/WebView2，管理页面监听 `127.0.0.1:8899`。详情见 `manager/README.md`。
- `qq_bot/NIKKE_QQ_BOT_MENU.ps1`：旧版总控菜单，作为兼容保留，新功能优先加到 `launcher/nikke_ctl.ps1`。
- `supports/AstrBot/start-astrbot.bat`：AstrBot WebUI 和本地模型代理启动入口（launcher 后台模式直接调用 astrbot.exe，不再经此 bat）。
- `qq_bot/02-start-qq-bot.bat`：启动会战桥接服务和成员后台（旧入口，launcher 后台模式已覆盖此能力）。
- `qq_bot/01-install-env.bat`：首次安装或修复 Python 依赖。

日常优先双击根目录 `start-nikke-qq-bot-menu.bat`，选 `[1] 日常上线`。低频维护项放在 `[5] 高级维护`，后台入口放在 `[3] 管理后台`。

## 目录边界

- `guild_war_bot/`：会战机器人业务逻辑、skills、SQLite 访问和 HTTP 桥接。
- `launcher/`：统一一键启动器（menu/start/stop/restart/status/admin/logs），后台模式日志进 `data/logs/`。
- `manager/`：图形管理客户端；只使用 Python 标准库 HTTP 服务和 pywebview，不引入第三方 Web 框架或前端构建链。
- `Skills/`：当前机器人已有能力的维护型 skill 清单，便于后续扩展和交接。
- `qq_bot/`：启动菜单、AstrBot 插件模板、旧 OneBot 回退入口。
- `data/`：SQLite、配置、OCR tessdata、轻量模板、集中日志（`data/logs/`）。
- `supports/AstrBot/`：AstrBot 配置、插件数据、Ollama 文本代理和启动脚本。
- `supports/NapCat.Shell.Windows.OneKey/`：NapCat/QQ 本地运行依赖。
- `supports/astrbot-uv-env/`：AstrBot Python 运行环境副本。
- `.venv/`：会战桥接和成员后台的本地 Python 依赖。

根目录不再保留 `AstrBot/` 或 `dependencies/` 旧依赖目录；AstrBot、NapCat 相关文件统一放在 `supports/`。

会战群命令统一走 `guild_war_bot/skills/` 的 `SkillRegistry`：文本命令在 `guild_war_bot/skills/guild_war.py`，截图命令在 `guild_war_bot/skills/game_progress.py`。`GuildWarBot.handle_message()` 只作为 CLI 和旧入口兼容层。

会战进度截图底层入口是 `game_progress_query.py`。当前识别增强参考 NIKKE MAA 资源：从 `F:\Codex\Nikke\Nikke_MAA\tools\android_maanikke_debug_apk\assets\MaaSync\MaaResource\resource\base\image\` 复制稳定模板到本项目 `data/templates/maa_nikke/`，运行时只依赖本项目内模板。新增页面识别时优先复用 MAA 模板/OCR 思路，再接入本地多模板匹配；不要把运行路径直接指向 `Nikke_MAA` 外部仓库。

AstrBot 插件开发要对齐 AstrBot 项目当前结构：插件目录使用 `metadata.yaml`、`main.py`、`_conf_schema.json` 和可选 `skills/`；插件类继承 `Star`，命令入口使用 `@filter.command`。本地 AstrBot v4.26 里 `register_star` 已标记废弃，不要为了注册插件再加 `@register` / `register_star`；元数据以 `metadata.yaml` 为准。

## 配置与权限边界

- AstrBot 配置主文件在 `supports/AstrBot/data/cmd_config.json`。
- AstrBot 插件配置由 `qq_bot/astrbot_plugin_nikke_guild_bridge/_conf_schema.json` 生成，已安装副本在 `supports/AstrBot/data/plugins/astrbot_plugin_nikke_guild_bridge/`；桥接地址和管理员 QQ 优先在 AstrBot WebUI 插件配置里维护。
- AstrBot 启动脚本优先使用 `supports/astrbot-uv-env/Scripts/astrbot.exe`，再回退 uv cache，最后才 `uvx --from astrbot`。
- 会战桥接和成员后台优先使用 `.venv/Scripts/python.exe`。
- NapCat 已放在 `supports/`，菜单会递归查找 `NapCatWinBootMain.exe`。
- Ollama 模型不打包进本目录，依赖本机 Ollama 服务和已拉取模型。
- 不要把 QQ 账号口令、NapCat token、模型 API key、管理员 QQ 号等敏感信息写进仓库文档。

## “机器人没反应”排障顺序

验收标准是 QQ 群里实际能收到回复，不是只看本地端口亮。

1. 查 Ollama：`11434` 是否可访问，`/api/tags` 是否有当前配置模型。
2. 查 AstrBot：`6185` 是否可访问，`supports/AstrBot/data/cmd_config.json` 的 provider 是否指向可用模型；必要时只重启 AstrBot。
3. 查 OneBot：`6199` 是否监听，并且 NapCat 到 AstrBot 有 Established WebSocket 连接。
4. 查 NapCat：QQ 小号是否在线，WebSocket 客户端地址是否为 `ws://127.0.0.1:6199/ws`。
5. 查插件：`astrbot_plugin_nikke_guild_bridge` 是否已在 `supports/AstrBot/data/plugins/`，并已在 AstrBot WebUI 重载/启用。
6. 查插件配置：`bridge.bridge_url` 是否指向 `http://127.0.0.1:8793`，管理员命令是否已在 `permissions.admin_qq_ids` 配置你的 QQ。
7. 查桥接：`8793/health` 是否 ok；用 `/command` 本地 POST 测 `/查刀`。
8. 查群内触发：群里是否 @ 到机器人或满足 AstrBot 当前唤醒/前缀规则，命令是否形如 `/查刀`、`/出刀 1200w`、`/会战进度查询`。

不要一上来重装 NapCat 或重写桥接；先定位消息卡在哪一层。

## 文档分工

- `README.md`：入口页，只说明从哪里开始。
- `README_BOT_PROJECT.md`：项目总览、端口、目录和核对状态。
- `qq_bot/README.md`：唯一的部署步骤和拓扑说明。
- `supports/README.md`：运行时依赖放置说明。
- 本文件：给后续 agent 的维护规则和当前事实。

## 编码约定

- `.bat` 和 `.cmd` 启动文件必须保持 ASCII-only + CRLF。
- 中文菜单、中文提示和复杂逻辑放进 `.ps1`。
- 不要把中文菜单写回 `.bat`，否则 Windows `cmd.exe` 可能把中文片段误当命令执行。

## 角色别名数据流（角色卡查询/养成建议）

- **权威数据源**：`F:\Codex\Nikke\Nikke_Wiki\exports\nikke_character_dictionary_with_images_updated.xlsx`（Codex 导出的角色卡登记表，含"别名"列，用户在此维护别名）。
- **同步脚本**：`tools/sync_aliases_from_xlsx.py` 读取 xlsx 别名列（`|` 和 `；;` 混合分隔，去自身名）→ 写入机器人侧 `data/character_aliases_extra.json`（**以 xlsx 为准**：xlsx 中该角色无有效别名则从补充表移除）。重跑：`PYTHONPATH=F:/Codex/Nikke/Nikke_Bot .venv/Scripts/python.exe tools/sync_aliases_from_xlsx.py`。
- **加载合并**：`guild_war_bot/wiki_query/index.py` 的 `WikiIndex.load()` 合并 `nikke_character_aliases.json`（Codex 源）+ `character_aliases_extra.json`（机器人侧）；`lookup()` 还支持去标点、倒序（暗影红莲）、部分匹配（女仆马斯特）兜底。
- **生效**：改完 extra 后需重启桥接服务（`guild_war_bot.service_http`，端口 8793）让新别名生效。
- **培养建议**：`data/character_meta.json` + `data/meta_crops/<角色名>.png`（屑夫蒂一图流 OCR 提取，`tools/build_character_meta.py` 重跑）；`/养成 <角色名>` 命令查询。

## 验证命令

```powershell
cd F:\Codex\Nikke\Nikke_Bot
.\start-nikke-qq-bot-menu.bat /health
$env:PYTHONPATH='F:\Codex\Nikke\Nikke_Bot'; py -3 -c "import guild_war_bot.service_http, guild_war_bot.admin_web; print('imports ok')"
Invoke-RestMethod http://127.0.0.1:11434/api/tags
Invoke-RestMethod http://127.0.0.1:8793/health
```

## 装备词条统计

词条功能只扩展 `astrbot_plugin_nikke_guild_bridge`，不修改 AstrBot 核心，也不把业务逻辑写进会战 `8793` 服务：

- 存储：`guild_war_bot/wiki_query/equipment_store.py`
- 会话：`guild_war_bot/wiki_query/equipment_session.py`
- OCR：`guild_war_bot/wiki_query/ocr.py`
- 卡片/对比/Excel：`guild_war_bot/wiki_query/catalog.py`
- AstrBot 路由：`qq_bot/astrbot_plugin_nikke_guild_bridge/main.py`
- 词条规则：`data/equipment_affix_catalog.json`
- 角色槽位：`data/character_equip_catalog.json`
- 模板与样本说明：`assets/equip_templates/README.md`
- 完整方案：`docs/词条统计功能实施方案.md`

命令支持半角/全角 `#`、`/` 前缀：`#词条导入 角色名`、`#词条导入 角色名 5`、`#词条 角色名`、`#词条统计 角色名或属性`、`#词条导出`、`#词条确认`、`#词条修正`、`#词条重试`、`#词条取消`。默认按 4 个装备槽位导入，只有角色配置或命令明确指定时使用 5 槽。

会话状态为 `IDLE -> WAITING_SCREENSHOT_N -> WAITING_CONFIRM -> COMPLETE`，30 分钟无交互清理；内存状态同时持久化到 SQLite。运行数据库固定使用 `StarTools.get_data_dir("astrbot_plugin_nikke_guild_bridge")/equipment_affix.db`，归档原图放在同一插件数据目录的 `imports/YYYYMMDD/<sha256>.<ext>`，不要写入会战库 `data/guild_war.db`。

消息入口必须在 5 秒内 ACK。OCR 全局最多 2 张/秒，同一 QQ 串行；RapidOCR、PIL 渲染和 Excel 导出使用后台任务/`asyncio.to_thread()`，后台不得保存整个 `AstrMessageEvent`。插件卸载时必须取消清理任务和后台任务。

词条阶数范围是 `0-15`，其中 `0` 代表待人工确认。`tier_values` 只有获得真实截图和可靠标定后才能填写，禁止恢复早期未经实测的 `tier_ranges`。当前 `assets/equip_templates/` 没有真实脱敏模板，QQ 压缩、反光和 UI 变化下的识别率尚未验收；离线测试通过不等于群内链路和识别率通过。

AstrBot 独立运行环境必须安装 `rapidocr-onnxruntime`。源码插件修改后，只同步插件源码到 `supports/AstrBot/data/plugins/astrbot_plugin_nikke_guild_bridge/`，不要覆盖 `supports/AstrBot/data/cmd_config.json` 或插件运行数据。验证命令：

```powershell
cd F:\Codex\Nikke\Nikke_Bot
py -3 -m pytest tests
py -3 -m compileall guild_war_bot qq_bot\astrbot_plugin_nikke_guild_bridge
$env:PYTHONPATH='F:\Codex\Nikke\Nikke_Bot'
& '.\supports\astrbot-uv-env\Scripts\python.exe' -c "import rapidocr_onnxruntime; import qq_bot.astrbot_plugin_nikke_guild_bridge.main; print('ok')"
```

2026-08-19 离线结果：`63 passed, 3 skipped`；AstrBot 环境插件导入和 RapidOCR 空白图冒烟通过。真实群聊/私聊图片、卡片和 Excel 发送仍需重载插件后在 QQ 链路验收。

## 图形管理客户端

主要文件：`manager/manager.py`、`manager/web/index.html`、`manager/web/style.css`、`manager/web/app.js`、`manager/start-manager.bat`。默认地址为 `http://127.0.0.1:8899`；占用时自动在后续 10 个端口中选择可用端口。调试也可临时设置 `NIKKE_MANAGER_PORT`。

客户端负责 AstrBot、NapCat、会战桥接、成员后台的启停与就绪等待；OneBot 6199 只做 Established 链路检测，故障归因到 NapCat，不提供独立启停。停止桥接/后台必须按监听端口找 PID，禁止杀全部 `python.exe`。用户手动停止服务后，本次客户端会话内暂停对应守护；手动启动或重启后恢复守护，避免刚停止就被自动拉起。

`manager/manager_config.json` 是本机运行配置，可能包含钉钉 webhook/secret，已加入 `.gitignore`；不要提交、复制到文档或写入测试输出。背景图片目录 `manager/manager_bg/` 同样忽略。配置写入使用临时文件替换，导入必须通过结构校验。

技能开关不是装饰状态：AstrBot 插件初始化时读取 `manager/manager_config.json` 中 `enabled=false` 的命令前缀，词条入口和会战/Wiki 桥接入口命中后拒绝执行。修改技能开关后需重载 `astrbot_plugin_nikke_guild_bridge` 或重启 AstrBot；新增技能只登记管理信息，不会自动生成对应业务实现。

管理器默认启动守护线程。只调试页面/API且不得启动机器人服务时使用：

```powershell
cd F:\Codex\Nikke\Nikke_Bot
$env:NIKKE_MANAGER_PORT=8900
& .\.venv\Scripts\python.exe .\manager\manager.py --no-webview --no-daemon
```

验证命令：

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_manager.py
& .\.venv\Scripts\python.exe -m pytest tests
& .\.venv\Scripts\python.exe -m compileall manager
```

2026-08-20 验证结果：管理器测试 `6 passed`；全量 `69 passed, 3 skipped`。桌面总览、技能弹窗、运维表格和 `760x900` 窄屏布局已通过本地浏览器检查，无横向溢出；原有 `8899` 管理器实例未被终止，新版使用 `8900` 隔离验证。PyInstaller `6.22.2` 已生成 `manager/NIKKE_Manager.exe`，并用 `--no-webview --no-daemon` 完成页面和 API 冒烟；当 `8899`、`8900` 已占用时，最终 EXE 已验证会自动顺延到 `8901`。
