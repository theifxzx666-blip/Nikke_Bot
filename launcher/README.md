# NIKKE QQ Bot 一键启动器（launcher）

把原来散落在根目录、`qq_bot/`、`supports/AstrBot/` 的多个入口统一到这里。

**日常只需要记住一个入口：**

```text
F:\Codex\Nikke\Nikke_Bot\start-nikke-qq-bot-menu.bat   ← 双击它（或双击本目录 menu.bat）
```

## 文件说明

| 文件 | 作用 | 日常频率 |
| --- | --- | --- |
| `menu.bat` | 交互控制台（推荐入口，一个窗口管全部） | ★ 每天 |
| `start.bat` | 一键启动（后台模式，窗口隐藏，日志进 data/logs） | ★ 每天 |
| `start.bat fg` | 一键启动（前台模式，弹窗便于调试） | 调试时 |
| `stop.bat` | 一键停止全部服务 | 收工时 |
| `restart.bat` | 一键重启 | 出问题时 |
| `status.bat` | 健康检查（端口/进程/桥接/OneBot 连接） | 排查时 |
| `admin.bat` | 打开全部后台页面（AstrBot/NapCat/桥接/成员后台） | 偶尔 |
| `logs.bat` | 打开集中日志目录 `data/logs/` | 排查时 |
| `nikke_ctl.ps1` | 核心控制脚本（start/stop/restart/status/logs/admin/menu 子命令） | 高级用户 |

## 相比旧方案的变化

| 痛点 | 旧方案 | 新方案 |
| --- | --- | --- |
| 入口分散 | 根目录 + qq_bot + supports 三处 | 统一到 `launcher/`，根目录一个入口 |
| 窗口太多 | AstrBot/文本代理/桥接/后台各弹一个窗 | 后台模式隐藏窗口，日志进 `data/logs/` |
| 无法一键停 | 只能手动关窗口 | `stop.bat` 一键按端口停止 |
| 日志分散 | 散在各窗口 | 集中 `data/logs/`，每个服务一个时间戳日志 |
| 重启繁琐 | 关窗口再逐个启动 | `restart.bat` 一键完成 |

## 后台模式说明

- `start.bat`（默认后台）：Ollama 检查（未运行则自动拉起，见下）→ NapCat → AstrBot + 文本代理 → 桥接 → 成员后台，全部隐藏窗口运行，输出重定向到 `data/logs/<服务名>_<时间戳>.log`。
- 唯一例外：**NapCat 需要可见窗口**（QQ 扫码登录），它按原方式弹出。登录成功后需确认 WebSocket 客户端地址为 `ws://127.0.0.1:6199/ws`。
- 后台模式下如果服务没起来，看对应日志文件即可，不用满桌找窗口。

## Ollama 自动拉起

`start.bat` 检测到 Ollama（11434）未运行时，会尝试自动启动，查找顺序：

1. 环境变量 `OLLAMA_EXE` 指向的 `ollama.exe`
2. PATH 中的 `ollama` 命令
3. 常见安装路径（`%LOCALAPPDATA%\Programs\Ollama`、`Program Files\Ollama` 等）

三种方式都找不到时，会提示手动启动，并给出设置 `OLLAMA_EXE` 的建议（适合便携版/自定义安装）。

关闭自动拉起：设置环境变量 `NIKKE_BOT_AUTO_OLLAMA=0`，则只提醒不启动。

## 常见问题

- **服务没起来**：先看 `data/logs/` 里对应服务的日志；端口状态用 `status.bat` 查看。
- **NapCat 6099 未监听**：NapCat 需要 QQ 登录，登录后确认 WebSocket 客户端地址 `ws://127.0.0.1:6199/ws`；若未自动弹出，可手动双击 `supports\NapCat.Shell.Windows.OneKey\bootmain\NapCatWinBootMain.exe`。
- **直接跑 ps1 报执行策略错误**：`.bat` 均已带 `-ExecutionPolicy Bypass`，正常双击不会遇到；仅在 PowerShell 中直接 `& .\launcher\nikke_ctl.ps1` 时才需先 `Set-ExecutionPolicy -Scope Process Bypass`。

## 子命令用法（高级）

```powershell
cd F:\Codex\Nikke\Nikke_Bot
powershell -NoProfile -ExecutionPolicy Bypass -File launcher\nikke_ctl.ps1 start
powershell -NoProfile -ExecutionPolicy Bypass -File launcher\nikke_ctl.ps1 start -Mode fg
powershell -NoProfile -ExecutionPolicy Bypass -File launcher\nikke_ctl.ps1 stop
powershell -NoProfile -ExecutionPolicy Bypass -File launcher\nikke_ctl.ps1 status
```

## 兼容性

- 根目录 `start-nikke-qq-bot-menu.bat` 现在优先指向 `launcher\menu.bat`；如果 launcher 不存在会自动回退旧菜单 `qq_bot\NIKKE_QQ_BOT_MENU.bat`，旧入口不会坏。
- `.bat` 全部 ASCII-only + CRLF；中文 UI 全部在 `nikke_ctl.ps1`（UTF-8 with BOM）。
