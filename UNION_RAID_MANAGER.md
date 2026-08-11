# NIKKE 联盟突袭管理台

统一入口：

```powershell
.\start-union-app.ps1
```

浏览器打开：

```text
http://127.0.0.1:8792/
```

当前整合内容：

- 读取现有 `data/guild_war.db` 成员、QQ 绑定、出刀记录。
- 读取现有 `data/union_sample.db` 队员采样结果，并支持同步到成员库。
- 挂接 `game_progress_query.py run` 做 Boss 进度截图采样。
- 挂接 `union_auto_sampler.py scan-game` 和 `assist-scan` 做成员采样。
- 新增 Boss 快照、出刀质量字段、后台任务日志。
- 可导出到 `data/exports/联盟突袭管理导出_*.xlsx`，并保留原模板中的历史 sheet。

建议使用顺序：

1. 打开管理台，确认成员绑定。
2. 如成员为空，先运行“队员自动采样”或“半自动采样”，再点“同步采样成员”。
3. 用“Boss 进度截图”采样当前进度，截图完成后在“手动校对 Boss 进度”补血量数字。
4. 在“出刀质量记录”里录入或校对成员伤害、Boss、阵容、尾刀。
5. 点击“导出 Excel”生成当前统计工作簿。

旧入口仍然保留：

- `python -m guild_war_bot.admin_web`：成员后台。
- `python union_member_sampler.py web`：队员采样录入页。
- `python -m guild_war_bot.onebot_http`：NapCat / OneBot 接口。
