# NIKKE 机器人管理客户端

Windows 桌面管理端，使用 Python 标准库提供本地 HTTP API，并通过 pywebview/WebView2 显示界面。默认监听 `http://127.0.0.1:8899`。
如果默认端口被旧实例占用，客户端会在 `8899-8909` 范围内自动选择下一个可用端口，并打开实际地址。

## 日常启动

双击：

```text
F:\Codex\Nikke\Nikke_Bot\manager\start-manager.bat
```

或在 PowerShell 中运行：

```powershell
cd F:\Codex\Nikke\Nikke_Bot
& .\.venv\Scripts\python.exe .\manager\manager.py
```

如果 pywebview 不可用，会降级到默认浏览器。仅调试 HTTP 页面且不允许守护线程启动/重启机器人服务时：

```powershell
& .\.venv\Scripts\python.exe .\manager\manager.py --no-webview --no-daemon
```

如果 `8899` 已被另一个管理器实例占用，可临时使用其他端口：

```powershell
$env:NIKKE_MANAGER_PORT=8900
& .\.venv\Scripts\python.exe .\manager\manager.py --no-webview --no-daemon
```

## 能力

- AstrBot、NapCat、会战桥接、成员后台的一键启停和就绪等待。
- AstrBot、NapCat、桥接健康页和成员后台统一打开入口。
- 技能清单、开关、添加和删除。
- 端口、进程、HTTP 健康和 OneBot Established 链路监控。
- 自动重启、退避、钉钉告警、恢复通知和最近 200 条事件。
- 配置导出、导入、恢复默认和本地背景图。

`manager_config.json` 包含本机钉钉密钥，已被 `.gitignore` 排除，不要提交或发送给其他人。
技能开关由 AstrBot 插件初始化时读取，修改开关后需在 AstrBot WebUI 重载 `astrbot_plugin_nikke_guild_bridge` 或重启 AstrBot。

## 打包

先安装打包工具：

```powershell
& ..\.venv\Scripts\python.exe -m pip install pyinstaller
```

在 `manager` 目录执行：

```powershell
& ..\.venv\Scripts\pyinstaller.exe --onefile --noconsole --name NIKKE_Manager --add-data "web;web" --hidden-import webview.platforms.edgechromium manager.py
```

将生成的 `dist\NIKKE_Manager.exe` 放在 `Nikke_Bot\manager\` 下运行，以便继续使用上级目录中的 `supports\` 和 `qq_bot\` 服务脚本。当前已生成：

```text
F:\Codex\Nikke\Nikke_Bot\manager\NIKKE_Manager.exe
```
