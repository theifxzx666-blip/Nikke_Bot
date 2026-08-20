# 机器人管理客户端 · 开发 Prompt（v2：pywebview 封装，不依赖浏览器）

> 本文件是生成 `manager.py + web/` 管理客户端的完整 Prompt。可直接喂给任何 AI 助手执行。

---

## 一、任务

开发一个 **NIKKE QQ 机器人管理客户端**（Windows 10，Python 3.13，PyInstaller 打包为 exe，双击即用、不依赖外部浏览器），具备：一键引导启动、管理后台集成、技能管理、运维监控（检测+自动重启+钉钉告警）、配置导出导入。

## 二、背景（现有服务）

- NapCat（QQ 协议，端口 6099，WebUI `http://127.0.0.1:6099`，用 `launcher-win10.bat` 启动需 UAC 提权 + 扫码登录）
- AstrBot（机器人框架，端口 6185，WebUI `http://127.0.0.1:6185`，用 `start-astrbot.bat` 启动）
- 会战桥接服务（端口 8793，健康检查 `http://127.0.0.1:8793/health` 返回 `ok=true`）
- 成员后台（端口 8788）
- OneBot 反向 WebSocket（端口 6199，NapCat 连它；`netstat` 里 6199 存在 `ESTABLISHED` 连接判定链路健康）

服务路径均在 `F:\Codex\Nikke\Nikke_Bot\`：
- `supports\AstrBot\start-astrbot.bat`
- `supports\NapCat.Shell.Windows.OneKey\launcher-win10.bat`
- `qq_bot\start-astrbot-bridge.bat`
- `qq_bot\02-start-qq-bot.bat`

管理客户端自身放在 `F:\Codex\Nikke\Nikke_Bot\manager\`，监听 `http://127.0.0.1:8899`。

## 三、技术栈（必须遵守）

- 后端：**Python 标准库**（http.server / ThreadingHTTPServer / json / subprocess / socket / urllib / hmac / hashlib / logging），**禁止第三方 Web 框架**
- 前端：**单页原生 HTML + CSS + JavaScript**，无构建工具、无 npm、无第三方 JS 库
- 窗口：**pywebview**（内嵌 WebView2）展示前端，`webview.create_window("NIKKE 机器人管理", "http://127.0.0.1:8899", width=1280, height=800, min_size=(1024,700))` + `webview.start()`；**默认不调用外部浏览器**（提供右上角"在浏览器打开"按钮可选，用 `webbrowser` 兜底）
- 若 pywebview 不可用则降级为 `webbrowser.open`，不崩溃

## 四、输出文件结构

```
F:\Codex\Nikke\Nikke_Bot\manager\
├── manager.py            # 入口：HTTP 服务 + 守护线程 + pywebview 窗口
├── manager_config.json   # 默认配置（运行时持久化用户设置）
├── manager_bg\           # 上传的背景图存储目录
├── manager.log           # 运行日志（按天轮转保留 7 天）
└── web\
    ├── index.html
    ├── style.css
    └── app.js
```

## 五、功能需求

### 1. 启动集成（一键引导）
- 总控【全部启动】【全部停止】【全部重启】+ 每个服务独立【启动/停止/重启】按钮
- 启动方式（`subprocess.Popen` + Windows `CREATE_NEW_CONSOLE`，cmd /c 调 bat）：
  - AstrBot → `cmd /c start-astrbot.bat`，cwd=`supports\AstrBot`
  - NapCat → `cmd /c launcher-win10.bat`，cwd=`supports\NapCat.Shell.Windows.OneKey`（提示 UAC、扫码）
  - 桥接 → `cmd /c start-astrbot-bridge.bat`，cwd=`qq_bot`
  - 成员后台 → `cmd /c 02-start-qq-bot.bat`，cwd=`qq_bot`
- 启动后轮询等待对应端口/健康检查就绪（NapCat 25s、AstrBot 40s、桥接 20s），给出成功/失败引导文案
- 停止：按端口找 PID（`netstat -ano`）后 `taskkill /F /PID`；NapCat 额外杀 `NapCatWinBootMain.exe` 与 `QQ.exe`；**严禁用杀 python.exe 的方式停桥接/后台（会误杀管理端自身）**

### 2. 管理后台集成
- 每服务【打开后台】按钮 → `webbrowser` 新标签页打开对应 WebUI URL（不 iframe）

### 3. 技能管理
- 技能清单存于 `manager_config.json`，默认预置：词条导入 `#词条导入`、词条统计 `#词条统计`、词条导出 `#词条导出`、角色查询 `#角色`、Wiki 查询 `#wiki`、养成建议 `#养成`
- 每项含 `name / desc / command / enabled`；开关切换 → `PUT /api/skills/<name>` 写配置，提示"重启插件生效"
- 添加技能 `POST /api/skills`（名称/描述/命令前缀/默认开启）
- 删除技能 `DELETE /api/skills/<name>`

### 4. 运维监控
- 后台守护线程每 `check_interval` 秒（默认 10）检测 5 项服务 + 1 项链路：
  - AstrBot：端口 6185 可连
  - NapCat：进程 `NapCatWinBootMain.exe` 存在 或 端口 6099
  - 桥接：GET `http://127.0.0.1:8793/health` 且 `ok=true`
  - 成员后台：端口 8788
  - OneBot 链路：`netstat` 6199 有 `ESTABLISHED`（故障时归因并尝试重启 NapCat）
- 连续失败 `fail_threshold` 次（默认 2）判定故障 → 自动重启 → 重试 `max_attempts` 次（默认 3），退避 `backoff_seconds`（默认 10/30/60）
- 3 次仍失败 → 钉钉告警（30 分钟冷却去重）；恢复后可发通知
- 事件历史：重启/告警/恢复/启停，内存保留最近 200 条，前端可查
- 设置项（`PUT /api/settings`）：检测间隔、失败阈值、重试次数/退避、钉钉 webhook/secret、冷却分钟、恢复通知开关

### 5. 配置导出导入
- `POST /api/export` → 返回 manager_config.json 内容供下载
- `POST /api/import` → 上传 JSON 恢复（校验合法性后写回）
- `POST /api/reset` → 恢复默认配置

## 六、钉钉告警（复用加签模式）

- URL：`https://oapi.dingtalk.com/robot/send?access_token=<token>`
- 加签：`timestamp`=毫秒；`sign`=HMAC-SHA256(key=secret, msg=`timestamp+"\n"+secret`) 的 base64 后 urlencode
- 拼 URL：`...&timestamp=<ts>&sign=<sign>`
- body：`{"msgtype":"markdown","markdown":{"title":"机器人守护告警","text":"..."}}`
- 同服务冷却 30 分钟；恢复通知可选

## 七、UI / 视觉规范（严格遵循）

- **扁平化**：无厚重阴影、细 1px 边框、圆角 16px、扁平线性图标、8px 间距体系
- **高斯模糊毛玻璃**：侧边栏/顶部栏/卡片/弹窗 `backdrop-filter: blur(18px) saturate(150%)`，半透明底 `rgba(255,255,255,0.55)`
- **背景图**：设置入口（右上角）→ 弹窗支持上传图片文件或填 URL，保存到配置全局生效；无背景时用深色渐变兜底
- 布局：左侧 220px 毛玻璃导航（总览 / 服务管理 / 技能管理 / 运维监控 / 配置）+ 主内容区
- 配色：主色 `#4F6EF7`，成功 `#22C55E`，警告 `#F59E0B`，错误 `#EF4444`，文字 `#1F2937` / `#6B7280`
- 状态：圆形小灯（绿/黄/红）+ 文字；开关滑块样式；全局 toast
- 响应式：桌面优先，窄屏侧边栏可折叠

## 八、API 设计

| Method | Path | 说明 |
|---|---|---|
| GET | `/` | 302 → `/web/` |
| GET | `/web/*` | 静态文件 |
| GET | `/bg` | 背景图文件（type=image 时） |
| GET | `/api/status` | 各服务状态 + 守护运行状态 |
| POST | `/api/services/start|stop|restart` | body `{service:"all"\|"astrbot"\|"napcat"\|"bridge"\|"admin"}` |
| GET | `/api/skills` | 技能清单 |
| POST | `/api/skills` | 添加 `{name,desc,command,enabled}` |
| PUT | `/api/skills/<name>` | `{enabled}` 开关 |
| DELETE | `/api/skills/<name>` | 删除 |
| GET | `/api/events` | 事件历史 |
| GET | `/api/settings` | 设置 |
| PUT | `/api/settings` | 保存设置 |
| POST | `/api/export` | 导出配置 JSON |
| POST | `/api/import` | 导入配置 JSON |
| POST | `/api/reset` | 恢复默认 |
| POST | `/api/background` | `{type:"upload",data:"base64"} \| {type:"url",url:"..."}` |

## 九、实现约束

- 仅标准库 + pywebview；子进程 `Popen` + `CREATE_NEW_CONSOLE`
- 守护线程与 HTTP 服务共存，任何异常不崩（try/except 包主循环）
- 日志 `manager.log` 按天轮转保留 7 天
- 前端 JS 用 `fetch` 轮询 `/api/status`（5 秒）
- 全部代码中文注释；**代码可直接运行**（`python manager.py`）；给出 PyInstaller 命令：
  `pyinstaller --onefile --noconsole --name NIKKE_Manager --add-data "web;web" --hidden-import webview.platforms.edgechromium manager.py`
