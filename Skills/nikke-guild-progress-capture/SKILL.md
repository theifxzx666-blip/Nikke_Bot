---
name: nikke-guild-progress-capture
description: Maintain the NIKKE guild raid progress screenshot skill. Use when working on /会战进度查询, /会战进度, /联盟突袭进度查询, game window automation, screenshot capture, async outbox image replies, or GameProgressSkill.
---

# 会战进度截图

## Scope

自动进入游戏联盟突袭界面，截图 Boss 血量进度，并通过 AstrBot 回传图片。这个能力已经是正式 `guild_war_bot/skills/` skill。

## User Commands

- `/会战进度查询`
- `/会战进度`
- `/联盟突袭进度查询`

## Runtime Path

- `guild_war_bot/skills/game_progress.py`
  - `GameProgressSkill`
  - `commands`
  - `handle()`
  - `_run()`
- `game_progress_query.py`
  - `capture_progress()`
  - `image_match_step_point()`
  - `locate_template()`
- `guild_war_bot/service_http.py`
  - `BridgeOutbox`
  - `BridgeReplyPort`
- 配置文件：`data/game_progress_query.config.json`
- MAA 模板目录：`data/templates/maa_nikke/`
- 默认输出目录：`data/game_progress_queries`

## Behavior

- 命令命中后先尝试获取单任务锁。
- 如果已有任务运行，立即返回“已有会战进度查询正在执行”。
- 成功入队后，后台线程执行 `capture_progress()`。
- 单图结果直接发送图片和说明；多图结果先发文字，再按 Boss I 到 V 逐张发送。
- 异步图片先写入桥接服务 outbox，再由 AstrBot 插件轮询并发送到群。
- 进入联盟/联盟突袭页面时优先使用 NIKKE MAA 模板识别，未命中才回退固定坐标。
- 如果识别到联盟突袭锁定/未开放模板，直接返回明确错误，避免继续盲点。

## Safety Rules

- 保留单任务锁，避免多条群消息同时控制游戏窗口。
- 自动化只应操作可见 NIKKE 窗口；不要加入登录绕过、注入、封包或内存读取。
- 修改坐标、模板或点击方式后，先用本机窗口手动验证，再接群命令。
- 新增页面识别优先复用 `Nikke_MAA` 的 `resource/base/image` 模板，再复制到本项目 `data/templates/maa_nikke/`，不要运行时依赖外部仓库路径。
- 图片路径必须是本机可访问绝对路径，供 AstrBot `image_result()` 发送。

## Verification

先确认桥接服务运行，再执行：

```powershell
Invoke-RestMethod http://127.0.0.1:8793/command -Method Post -ContentType "application/json" -Body (@{
  text = "/会战进度查询"
  sender_name = "测试成员"
  sender_qq = "10001"
  session_id = "skill-progress-check"
} | ConvertTo-Json -Compress)
```

随后轮询：

```powershell
Invoke-RestMethod "http://127.0.0.1:8793/outbox?session_id=skill-progress-check&after=0"
```

确认 outbox 中出现 `image` 消息。
