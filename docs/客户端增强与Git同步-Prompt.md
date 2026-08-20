# NIKKE 机器人管理客户端增强 + Git 同步 —— 开发 Prompt

> 适用场景：已有 `NIKKE_Manager.exe` 管理客户端（`F:\Codex\Nikke\Nikke_Bot\manager\`，Python 标准库 http.server + pywebview 内嵌 WebView2 + 单页原生前端），需做三项增强后重新打包。

## 背景与现状

- 管理客户端：`manager/manager.py`（后端，REST API + 守护线程）+ `manager/web/{index.html,style.css,app.js}`（前端）+ `NIKKE_Manager.exe`（PyInstaller 单文件打包，psutil 已内置，检测无弹窗）
- 服务链路：NapCat(6099) → OneBot WS(6199) → AstrBot(6185) → 会战桥接(8793) / 成员后台(8788)
- NapCat 启动方式：`supports/NapCat.Shell.Windows.OneKey/launcher-win10.bat` → `NapCatWinBootMain.exe <QQ路径> <inject.dll>`，即**机器人账号的 QQ.exe 是 NapCatWinBootMain.exe 的子进程**；用户自己登录的 QQ 是独立进程（父进程为 explorer/cmd）
- Git：本地仓库已存在，remote = `https://github.com/theifxzx666-blip/Nikke_Bot.git`，远程 main 已同步到 `55155ff`
- 敏感文件：`manager/manager_config.json`、`watchdog_config.json` 含钉钉 webhook/secret，`.gitignore` 已排除，**不得提交**

---

## 需求 1：精准停止 NapCat —— 只关机器人账号的 QQ，不误杀用户 QQ

### 问题
`manager.py` 的 `kill_process("QQ.exe")` 按进程名全杀，会把用户自己登录的 QQ 账号进程一起关掉。

### 要求
实现 `kill_napcat_tree() -> bool`：
1. 遍历 psutil 进程，收集所有 `NapCatWinBootMain.exe` 进程，并**递归收集其子进程**（`proc.children(recursive=True)`，其中包含被它拉起的机器人账号 QQ.exe）的 PID；
2. 兜底：若 NapCatWinBootMain 已不存在但残留 QQ.exe，仅当该 QQ.exe 的**父进程链中出现过 NapCatWinBootMain.exe** 时才纳入击杀（防止父进程退出后 reparent 导致漏杀）；
3. 先杀 NapCatWinBootMain 进程树（含子），再按收集的 QQ PID 兜底杀一次；
4. **绝不**按 `QQ.exe` 进程名全杀——用户自己登录的 QQ 全程不受影响；
5. `stop_service` 中 napcat 服务改为调用 `kill_napcat_tree()`（替代原 `stop_processes: ["NapCatWinBootMain.exe", "QQ.exe"]` 的按名全杀），其他服务（bridge/admin 按端口杀、astrbot 按进程名杀）逻辑不变；
6. 保持 stop 后的"等待真正退出（最多 8s）→ 刷新状态"逻辑不变。

### 验证
- 起一个普通 python 进程作为"假用户进程"，`kill_napcat_tree()` 后它必须存活；
- napcat 停止后 6099 端口释放、NapCatWinBootMain.exe 和机器人 QQ.exe 消失；
- 状态 API 如实反映离线。

---

## 需求 2：Git 仓库同步 —— 防止代码写错无法回滚

### 问题
有大量未提交改动（manager/、watchdog.py、qrcode_watch.py、docs、guild_war_bot/wiki_query 新增模块、tests 等），且 PyInstaller 的 `build_tmp*/dist_tmp*` 中间目录**未被 .gitignore 覆盖**，直接 `git add -A` 会误提交大量构建垃圾。

### 要求
1. 完善 `.gitignore`（追加）：
   - `manager/build_tmp*/`、`manager/dist_tmp*/`、`manager/build/`、`manager/dist/`
   - `manager/manager.log`、`manager/manager_logs/`、`manager/manager_bg/`
   - `data/cmd_config.json`（含 token/secret，不提交）
   - 确认 `manager/manager_config.json`、`watchdog_config.json`、`manager/NIKKE_Manager.exe`、`manager/*.spec` 已在忽略清单
2. `git add -A` 前先 `git status` 复核：不得出现任何含 `secret/token` 的配置文件、不得出现 `build_tmp*/dist_tmp*` 目录、不得出现 `.venv/`/`supports/` 运行依赖
3. 提交并推送：
   - 提交信息按现有规范（`feat:` / `fix:` / `chore:` 前缀，中文描述）
   - `git push origin main`
4. 推送后 `git log --oneline -3` 确认同步，远程 `git ls-remote` 确认 commit hash 一致

### 验证
- `git status` 干净（无待提交）；
- `git ls-remote --heads origin` 的 HEAD 与本地最新 commit 一致；
- 远程仓库不包含任何敏感配置。

---

## 需求 3：启动 cmd 集成到客户端 —— 一个入口管所有

### 问题
散落的启动/管理能力还在 bat/ps1 里（首次安装依赖 `qq_bot/01-install-env.bat`、各服务后台页、NapCat 二维码登录监控 `launcher/qrcode_watch.py`、服务日志），用户在客户端里看不到。

### 要求
在客户端**运维监控页**新增"系统工具"卡片区（后端加 API、前端加按钮，视觉沿用现有毛玻璃/扁平化风格）：

| 按钮 | 行为 |
|---|---|
| 安装依赖 | `POST /api/system/install_deps` → 静默（`CREATE_NO_WINDOW` + 输出重定向到 `manager_logs/install.log`）Popen `qq_bot/01-install-env.bat`（cwd=`qq_bot`），返回已启动提示 |
| 打开管理后台 | 复用现有 `POST /api/open_service`（AstrBot 6185 / NapCat WebUI 6099 / 成员后台 8788 / 桥接健康页 8793/health），前端下拉或按钮组 |
| 查看二维码 | `GET /api/qrcode/status` 返回 `supports/NapCat.Shell.Windows.OneKey/cache/qrcode.png` 是否存在+修改时间；`GET /api/qrcode/image` 返回该 png（不存在返回 404）；前端弹窗显示图片并提示"扫码登录；如已刷新请点刷新重新加载" |
| 查看日志 | `GET /api/system/logs` 返回 `manager.log` 与 `manager_logs/*.log` 各文件最后 N 行（N=50），前端弹窗 tab 展示 |

- 后端在 `manager.py` 增加以上 4 个 API（保持标准库，用 `subprocess` 时一律 `CREATE_NO_WINDOW` + 文件重定向，不得弹窗）
- 前端在 `index.html` 运维页加"系统工具"卡片，`app.js` 实现交互（fetch + toast + 弹窗），全部原生 JS
- 打包：PyInstaller 用新 `--workpath/--distpath` 目录（避免 safe-delete 拦截），覆盖 `NIKKE_Manager.exe`

### 验证
- 4 个新 API 冒烟通过（curl）；
- `POST /api/system/install_deps` 不弹窗、写 install.log；
- `/api/qrcode/status` 能正确反映 qrcode.png 是否存在；
- 重新打包后 exe 内页面含"系统工具"卡片。

---

## 交付物
1. `manager/manager.py`（含 kill_napcat_tree + 4 个系统 API）
2. `manager/web/index.html`、`manager/web/app.js`（运维页系统工具卡片）
3. `.gitignore`（补充忽略项）
4. Git 提交并推送成功
5. 重新打包的 `NIKKE_Manager.exe`

## 约束
- 不修改 AstrBot/NapCat/QQ 任何既有文件
- 检测/启停全程 psutil + CREATE_NO_WINDOW，零弹窗
- 敏感配置不进入 git
