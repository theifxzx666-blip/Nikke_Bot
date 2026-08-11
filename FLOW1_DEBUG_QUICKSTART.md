# 流程1采样调试入口

调试阶段优先用这些入口，不需要先关心后台管理台能不能完整串起来。

## 一键离线验证

双击：

`F:\Codex\Nikke\Nikke_Bot\flow1-debug-sample.bat`

作用：

- 使用固定素材图验证 OCR、Boss 识别、伤害识别、CSV 输出。
- 不会操作游戏窗口。
- 输出到 `F:\Codex\Nikke\Nikke_Bot\data\flow1_debug`。

## 一键实机调试

先在游戏中手动打开：

`联盟 -> 联盟突袭 -> 联盟记录`

然后双击：

`F:\Codex\Nikke\Nikke_Bot\flow1-debug-live.bat`

作用：

- 打开可见管理员 PowerShell 窗口。
- 默认采 3 屏，每屏按 6 条记录处理。
- 拖动起点在第 6 条记录卡片内部，避免碰到弹窗底部边框。
- 默认拖动距离是 `6.1` 行，终点比例是 `0.16`。
- 每次实机采样会在对应 `page_xx` 目录写出 `drag_plan.png`，用于复盘脚本实际计划从哪里拖到哪里。
- 默认认为“联盟记录”弹窗已经打开。

## 固定调试产物

固定调试目录：

`F:\Codex\Nikke\Nikke_Bot\data\flow1_debug`

每次运行后重点看这些文件：

- `latest_paths.txt`：最新一次运行的完整路径索引
- `latest_records.csv`：最新逐刀明细
- `latest_attendance.csv`：最新成员出刀汇总
- `latest_records.json`：最新结构化调试数据
- `latest_operation.log`：最新操作日志

真实 session 目录在：

`F:\Codex\Nikke\Nikke_Bot\data\flow1_debug\runs\<session_id>\`

其中会包含每屏截图、每行截图、字段截图、CSV、JSON、operation.log。

## 相关测试素材

素材目录：

`D:\Codex\依赖\Nikke素材采样\联盟采样\联盟突袭\采集链路1`

核心素材：

- `联盟_联盟突袭_活动主页_联盟记录_伤害明细.png`
- `联盟_联盟突袭_活动主页_联盟记录_明细.png`
- `联盟_联盟突袭_活动主页_联盟记录.png`

## 给 Codex 复盘时优先发这些

优先给：

1. `data\flow1_debug\latest_operation.log`
2. `data\flow1_debug\latest_records.csv`
3. `data\flow1_debug\latest_paths.txt`

如果是识别错行/错数字，再给对应 session 目录里的 `screen.png` 或 `row.png`。

## 已验证拖动参数

2026-06-13 实机验证通过的拖动参数：

- 每屏记录：`6`
- 拖动行：`6`
- 拖动距离：`6.1`
- 拖动步数：`56`
- 拖动时长：`1.4s`
- 终点比例：`0.16`

代表性日志：

`拖动坐标：(398,1010) -> (398,333)，56 步/1.4s。`

这组纵坐标移动已确认能精准对齐一整页记录，后续优先保持不动。
