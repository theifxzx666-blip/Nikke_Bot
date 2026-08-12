# NapCat + AstrBot 升级方案

目标：把现有 Q 群会战机器人升级为“Laplace 人格 + 日常查询 + 会战 skill”的群内助手，同时尽量保持免费、本地可控、低风险。

## 推荐结论

第一版建议走并行升级：

```text
QQ 小号
  -> NapCat
  -> AstrBot OneBot v11
  -> 人格/闲聊/权限/插件调度
  -> 本项目本地桥接服务
  -> GuildWarBot / skills / SQLite / 游戏截图自动化
```

不要让 AstrBot 直接改 SQLite，也不要把会战逻辑重写进 AstrBot 插件。现有 `GuildWarBot` 和 `guild_war_bot/skills/` 已经是清晰的业务边界，AstrBot 只需要把群消息转成桥接请求。

## 组件分工

| 组件 | 职责 | 免费策略 |
| --- | --- | --- |
| NapCat | 登录 QQ 小号，收发群消息，提供 OneBot v11 能力 | 本地运行 |
| AstrBot | 人格、LLM、插件调度、群管式入口 | 本地运行 |
| 模型服务 | 拉普拉斯风格闲聊、自然语言改写、命令解释 | 优先 Ollama/LM Studio 本地模型；云端免费额度只作为备选 |
| 本项目桥接服务 | 执行 `/查刀`、`/出刀`、`/提醒未出刀`、`/会战进度查询` 等业务能力 | 本地运行 |
| SQLite | 公会成员、QQ 绑定、出刀记录 | 继续使用 `data/guild_war.db` |

## 第一阶段拓扑

### NapCat 到 AstrBot

在 AstrBot WebUI 新增消息平台：

```text
平台类型：OneBot v11
协议：反向 WebSocket
监听地址：0.0.0.0
监听端口：6199
路径：/ws
```

在 NapCat WebUI 新增网络配置：

```text
类型：WebSocket 客户端
地址：ws://127.0.0.1:6199/ws
```

如果保留旧 Python OneBot 机器人做对照，不要让同一个 NapCat 账号同时把同一条消息上报到 AstrBot 和旧 HTTP 机器人，否则会出现双回复。旧 HTTP 入口 `python -m guild_war_bot.onebot_http` 可以先留作回退方案。

旧 NapCat HTTP 直连启动文件已经收进：

```text
qq_bot/legacy_onebot/
```

### AstrBot 到本项目

本项目新增了一个本地 HTTP 桥接服务。日常不要手动拆命令启动，优先用本目录的启动入口：

```powershell
cd F:\Codex\Nikke\Nikke_Bot
.\qq_bot\02-start-qq-bot.bat
```

默认地址：

```text
http://127.0.0.1:8793
```

健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8793/health
```

首次部署或换机器时先运行依赖安装入口：

```powershell
cd F:\Codex\Nikke\Nikke_Bot
.\qq_bot\01-install-env.bat
```

发送命令：

```powershell
Invoke-RestMethod http://127.0.0.1:8793/command -Method Post -ContentType "application/json" -Body (@{
  text = "/查刀"
  sender_name = "群名片"
  sender_qq = "123456"
  is_admin = $false
  session_id = "qq-group-123"
} | ConvertTo-Json -Compress)
```

异步 skill 输出，例如会战进度截图，走 outbox 轮询：

```powershell
Invoke-RestMethod "http://127.0.0.1:8793/outbox?session_id=qq-group-123&after=0"
```

返回的图片路径是 Windows 本地绝对路径，AstrBot 插件需要按平台 API 发送图片。

本目录也放了一个 AstrBot 插件模板：

```text
astrbot_plugin_nikke_guild_bridge/
```

把这个目录复制到 `supports/AstrBot/data/plugins/` 后，在 AstrBot WebUI 重载插件即可。插件默认访问 `http://127.0.0.1:8793`，也可以用环境变量 `NIKKE_GUILD_BRIDGE_URL` 改地址。

当前插件按 AstrBot 官方插件形态维护：

- `metadata.yaml` 用于插件元数据。
- `main.py` 继承 `Star`，用 `@filter.command` 注册命令。
- `_conf_schema.json` 让 AstrBot WebUI 管理桥接地址、轮询参数和管理员 QQ。
- `skills/` 暴露插件内置 skill 说明给 AstrBot Skill Manager。

优先在 AstrBot WebUI 的插件配置里维护 `bridge.bridge_url` 和 `permissions.admin_qq_ids`；环境变量只作为兜底兼容。

## AstrBot 插件策略

插件只做四件事：

1. 识别会战相关命令：`/查刀`、`/出刀 1200w`、`/提醒未出刀`、`/会战进度查询`。
2. 把命令 POST 到 `http://127.0.0.1:8793/command`。
3. 立即发送 `reply`。
4. 如果是异步任务，用 `session_id` 轮询 `/outbox`，把 text/image 再发回群里。

这样后续新增 skill 时，优先在 `guild_war_bot/skills/` 加 Python 能力；AstrBot 插件不膨胀。

## Laplace 人格设定

建议在 AstrBot 的人格/系统提示词里使用“像拉普拉斯，但不直接冒充官方角色”的写法，降低版权和违和风险：

```text
你是公会群里的英雄型作战支援机器人，语气热血、正义、直接、稍微中二。
你喜欢把成员称作指挥官、队友或英雄候补。
你会主动鼓励大家完成联盟突袭、日常清单和信息查询。
你不编造游戏数据；涉及出刀、成员、Boss、伤害、截图时必须调用工具或要求用户提供信息。
你不能执行购买、招募、账号登录、绕过风控、刷屏或骚扰成员的行为。
群聊回复要短，优先 1 到 4 句；需要严肃提醒时收起玩笑。
```

示例语气：

```text
收到，指挥官！我来检查今日会战进度。
英雄部队还差 12 刀，未出满名单如下。
这条情报我还没有证据，不能胡乱宣布胜利。
```

## 日常查询能力排序

第一批保留现有稳定能力：

- `/帮助`
- `/查刀`
- `/查刀 成员名`
- `/出刀`
- `/出刀 1200w`
- `/提醒未出刀`
- `/催刀`
- `/日报`
- `/伤害榜`
- `/会战时间`
- `/会战进度查询`

第二批再接资料库查询：

- `/角色 红莲`：从根目录 `nikke_character_dictionary_enhanced.json` 查角色卡。
- `/队伍 文案`：生成简短配队记录或读取已有队伍图。
- `/活动日历`：先手动维护 JSON，不要一开始就做网页抓取。

## 风险边界

- 用 QQ 小号，不用主号。
- 群内先测试群验证，再接正式公会群。
- 默认被动回复；不要高频主动推送。
- 管理员命令优先依赖 AstrBot 插件配置 `permissions.admin_qq_ids`，环境变量 `ADMIN_QQ_IDS` 或 `NIKKE_GUILD_ADMIN_QQ_IDS` 只作为兜底。
- 会战截图和游戏窗口自动化仍属于高风险 skill，保留单任务锁，避免多条群消息同时控制鼠标。
- 不把模型 API Key、QQ token、NapCat token 写入仓库。

## 分阶段实施

### V1：接入与保底

- NapCat 只连 AstrBot。
- AstrBot 配好人格和免费/本地模型。
- 启动 `02-start-qq-bot.bat`。
- AstrBot 插件只桥接现有命令。
- 旧 `onebot_http.py` 保留，不同时接同一个群。

### V2：查询扩展

- 在 `guild_war_bot/skills/` 新增角色资料查询 skill。
- 输出短文本卡片，不先做复杂图片。
- 加测试，避免 GameKee 缓存字段变化导致群里报错。

### V3：主动提醒

- 只对管理员开启。
- 默认在联盟突袭前 2 天使用。
- 加冷却、白名单和人工确认，避免刷屏。

## 参考入口

- 用户提供的 B 站教程：`https://www.bilibili.com/opus/1178906542124040193`
- NapCat 项目：`https://github.com/NapNeko/NapCatQQ`
- NapCat 文档：`https://napneko.github.io/`
- AstrBot 文档：`https://docs.astrbot.app/`
- AstrBot OneBot v11 文档入口：`https://docs.astrbot.app/platform/aiocqhttp`
- AstrBot 插件开发入口：`https://docs.astrbot.app/dev/star/plugin-new`

## NapCat 掉线 / 快速登录处理（2026-08-12 实战记录）

### 现象判断

- **假在线**：进程还在、`6099`/`6199` 端口在，但机器人不回消息 → QQ 登录态失效（腾讯踢号/过期），NapCat 收不到也不上报新消息。
- **真掉线**：`6099` 不再监听 → NapCat/QQ 进程没了，需要重启。

### 快速登录的正确方式

**用官方脚本**（不要手动起 `NapCatWinBootMain.exe`）：

```bat
supports\NapCat.Shell.Windows.OneKey\launcher-win10-user.bat 1255348850
```

要点：

1. `autoLoginAccount` 已配置为 `1255348850`（`webui.json`），NapCat 启动时**自动快速登录**该账号，无需手动传 `-q`。
2. NapCat 会检测本机可快速登录的账号列表并自动选择小号（日志可见：`自动快速登录成功: 1255348850`）。
3. **NapCat 小号数据目录在 D 盘**：`D:\Software Datas\Tencent Files\Tencent Files\NapCat\data`（不是 C 盘 QQ 目录，排查凭证时别找错）。

### 常见坑

- 手动执行 exe 注入会导致残留僵尸 QQ 进程（约 20MB、杀不掉、窗口标题"退出"），卡死后续启动 → 优先用官方 bat，别手动起 exe。
- 若出现多个 `NapCatWinBootMain.exe` 实例，先全部停掉再启动一个。
- 快速登录失败需重新扫码时：`launcher-win10-user.bat`（不带参数）会弹二维码窗口，扫码后凭证落盘，之后自动快速登录恢复。
