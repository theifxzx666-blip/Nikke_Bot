# 拉普拉斯机器人 · 落地操作文档（Checklist）

> 关联文档：
> - `prompts/laplace_system_prompt.md` —— 系统提示词（v1.1）
> - `prompts/implementation_architecture.md` —— 落地方案架构（v1.0）
> 本文件定位：**落地执行手册**。按「落地前 → 落地时 → 落地后」三个阶段操作，每步含验证命令与验收标准。
> 日期：2026-08-11

---

## 〇、三阶段总览

```text
落地前（准备）          落地时（实施）            落地后（运维）
─────────────          ─────────────            ─────────────
□ 1. 环境健康核查        □ P1 本地角色查询         □ 1. 日常巡检
□ 2. 数据源核查          □ P2 在线兜底             □ 2. 数据更新
□ 3. 代码配置准备        □ P3 培养建议             □ 3. 内容维护
□ 4. 内容数据准备        □ P4 日常更新             □ 4. 排障手册
□ 5. 权限账号准备        □ P5 前哨基地             □ 5. 版本记录
□ 6. 备份               □ P6 回归加固
```

原则：
- **先测试群，后正式群**；正式公会群落地前必须先在测试群完整跑通 P1。
- **每阶段独立验收**，验收不通过不进入下一阶段。
- 全程使用 QQ 小号，不碰主号。

---

# 一、落地前（准备阶段）

> 目标：确认环境全绿、数据就位、权限明确、有备份可回滚。**不满足条件不启动落地。**

## 1.1 环境健康核查（必须全绿）

| # | 检查项 | 检查命令 | 期望结果 |
| --- | --- | --- | --- |
| 1 | Ollama 服务 | `Invoke-RestMethod http://127.0.0.1:11434/api/tags` | 返回模型列表，含配置的模型（当前为 qwen3.5:2b） |
| 2 | AstrBot WebUI | 浏览器打开 `http://127.0.0.1:6185` | 可登录，人格配置已粘贴 prompt v1.1 |
| 3 | NapCat WebUI | 浏览器打开 `http://127.0.0.1:6099` | 可登录，QQ 小号在线 |
| 4 | OneBot WS 连接 | AstrBot 平台日志 | 显示「适配器已连接」 |
| 5 | 会战桥接服务 | `Invoke-RestMethod http://127.0.0.1:8793/health` | 返回 ok |
| 6 | 成员后台 | 浏览器打开 `http://127.0.0.1:8788` | 可访问 |
| 7 | 本地导入 | `$env:PYTHONPATH='F:\Codex\Nikke\Nikke_Bot'; py -3 -c "import guild_war_bot.service_http, guild_war_bot.admin_web; print('imports ok')"` | 输出 imports ok |

**核查记录**（填表确认）：

```text
Ollama 模型名：__________（若与实际不符，先改 AstrBot 模型配置再继续）
QQ 小号在线：□ 是 □ 否
AstrBot 人格已粘贴 v1.1：□ 是 □ 否
桥接 8793：□ ok □ 异常
```

## 1.2 数据源核查（Nikke_Wiki）

检查以下 5 个文件存在且可解析（缺失 = 本地查询无法工作，P1 不可开始）：

| 文件 | 作用 | 缺失后果 |
| --- | --- | --- |
| `F:\Codex\Nikke\Nikke_Wiki\data\nikke_character_dictionary_enhanced.json` | 角色主数据（191 角色×46 字段） | 角色查询全挂 |
| `F:\Codex\Nikke\Nikke_Wiki\data\nikke_character_aliases.json` | 别名归一化 | 黑话昵称查不到 |
| `F:\Codex\Nikke\Nikke_Wiki\data\nikke_characters.json` | 基础属性索引 | 快速属性查询不可用 |
| `F:\Codex\Nikke\Nikke_Wiki\data\cn_release_status.json` | 国服上线状态 | 抽卡建议缺少依据 |
| `F:\Codex\Nikke\Nikke_Wiki\data\nikke_campaign_stage_summary.json` | 关卡概要（P5 用） | 前哨基地本地估算不可用 |

**校验命令**：

```powershell
cd F:\Codex\Nikke\Nikke_Wiki
py -c "import json,io; [json.load(io.open('data/'+f, encoding='utf-8')) for f in ['nikke_character_dictionary_enhanced.json','nikke_character_aliases.json','nikke_characters.json','cn_release_status.json']]; print('5 files: parse ok')"
```

> 注意：部分 JSON 带 UTF-8 BOM，读取必须用 `encoding='utf-8'` 或 `utf-8-sig`。校验失败先检查编码，不要直接改文件。

## 1.3 代码与配置准备

- [ ] 确认 `guild_war_bot/skills/registry.py` 的 `default_registry()` 结构，确认新增技能注册方式（参照 `Skills/README.md` 维护顺序）。
- [ ] 确认 `guild_war_bot/service_http.py` 的 `/command` 路由可扩展（新增技能不需改路由，技能注册即可）。
- [ ] 确认 AstrBot 插件 `_conf_schema.json` 支持新增 alias（`/角色` `/培养` `/更新` `/基地`）。
- [ ] 确认 `data/` 下无同名 `character_meta.json` 冲突。

## 1.4 内容数据准备（P3 前置，建议提前做）

屑夫蒂一图流是图片，OCR 不稳定，**培养建议采用人工录入**：

- [ ] 建立 `data/character_meta.json` 空骨架（结构见架构文档 3.3）。
- [ ] 优先录入**热度 Top20 角色**（群内常用：红莲、神罚、拉普拉斯、麦斯威尔、德雷克、白兔…按群内实际讨论频率定）。
- [ ] 每条记录标注 `source`（屑夫蒂一图流版本）+ `updated`（录入日期）。
- [ ] 录入完成后群内抽查 3~5 个角色确认结论无错。

> 未录入的角色在 P3 阶段会明确回复「该角色培养资料暂未收录」，不算缺陷，但要在 `/帮助` 里说明数据覆盖范围。

## 1.5 权限与账号准备

- [ ] 管理员 QQ 列表确认：AstrBot 插件配置 `permissions.admin_qq_ids`（优先维护位置），兜底环境变量 `ADMIN_QQ_IDS` / `NIKKE_GUILD_ADMIN_QQ_IDS`。
- [ ] 测试群就绪：一个成员可控、便于刷消息的群（可自建群）。
- [ ] 正式群名单确认：落地 P1 通过后才拉正式公会群。
- [ ] 敏感信息检查：确认仓库内无 QQ token / NapCat token / API key（`git grep -i "token\|secret\|password"` 自查，若有先清除）。

## 1.6 备份（必须执行）

落地前对以下内容做一次快照，便于回滚：

```powershell
# 到 Nikke_Bot 根目录
cd F:\Codex\Nikke\Nikke_Bot
$ts = Get-Date -Format "yyyyMMdd_HHmm"
# 会战数据库（核心业务数据）
Copy-Item data\guild_war.db "data\backup\guild_war_$ts.db" -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force data\backup | Out-Null
Copy-Item data\guild_war.db "data\backup\guild_war_$ts.db"
# 现有 skills 目录（代码回滚点）
Copy-Item -Recurse guild_war_bot\skills "data\backup\skills_$ts"
# AstrBot 插件配置
Copy-Item supports\AstrBot\data\plugins\astrbot_plugin_nikke_guild_bridge\_conf_schema.json "data\backup\bridge_conf_$ts.json" -ErrorAction SilentlyContinue
```

- [ ] 备份完成，确认 `data/backup/` 下有 `guild_war_<时间>.db` 与 `skills_<时间>/`。
- [ ] 如果项目有 git，落地前打 tag：`git tag pre-laplace-launch && git push origin pre-laplace-launch`。

## 1.7 落地出门条（全勾才允许进入「落地时」）

```text
□ 1.1 环境核查 7 项全绿
□ 1.2 数据源 5 文件解析通过
□ 1.3 代码配置确认可扩展
□ 1.4 character_meta.json 已建骨架（Top20 可后补，P3 前完成）
□ 1.5 管理员 QQ、测试群就绪
□ 1.6 备份完成
```

---

# 二、落地时（实施阶段）

> 按 P1→P6 顺序执行，每阶段完成「代码 + 本地测试 + 测试群实测」三步。**任何一步失败先排查，不跳过。**

## P1 本地角色查询（地基，必须最先）

**操作**：
1. 新建 `guild_war_bot/wiki_query/` 包：`index.py`（WikiIndex 三索引）、`normalizer.py`（别名归一化）、`summarize.py`（角色卡摘要）、`cache.py`（TTL 缓存）。
2. 新建 `guild_war_bot/skills/nikke_wiki.py`：实现 `/角色 <名>`、`/wiki <词>`。
3. 在 `registry.py` 的 `default_registry()` 注册新技能。
4. 新建 `tests/test_wiki_query.py`：索引加载、别名命中、未知角色返回友好提示。

**验收**：
- 本地测试：`pytest tests/test_wiki_query.py` 全绿。
- 测试群实测：`/角色 红莲` → 秒回角色卡（职业/爆裂/元素/国服状态/头像）。

**回滚**：删除 `wiki_query/` 与 `nikke_wiki.py`，恢复 registry 即可，不影响会战功能。

## P2 在线兜底（GameKee）

**操作**：
1. `wiki_query/gamekee.py`：用增强词典中的 `gamekeeEntryId` / `gamekeeContentId` 拼详情 URL；命中 `Nikke_Wiki/cache/gamekee_content_details/` 先读缓存；未命中在线抓取（requests + 8s 超时 + UA + 节流 ≥1s）。
2. `wiki_query/summarize.py` 增加网页正文清洗（剥 HTML/脚本/广告，≤4 句转述 + 来源链接）。
3. 抓取走后台线程，先回「正在查询，指挥官稍等」，沿用 `/会战进度查询` 异步模式。

**验收**：
- 本地测试：mock 一个 GameKee 详情页，验证清洗与缓存写入。
- 测试群实测：`/角色 <本地词典没有的名字>` → 在线返回 ≤4 句摘要 + 来源链接。
- 断网测试：kill 网络 → 明确回复「暂时连接不上」，不编造。

**回滚**：`gamekee.py` 返回 None 时降级为本地查询 + 友好提示，删除在线逻辑不影响 P1。

## P3 培养建议（character_meta + nikke_meta）

**操作**：
1. 确保 `data/character_meta.json` 已录入（至少 Top20，见 1.4）。
2. 新建 `guild_war_bot/skills/nikke_meta.py`：`/培养 <名>`、`/抽卡 <名>`，输出四段式（抽卡→T10词条→珍藏品→过渡/终极加点）+ 来源标注。
3. 数据缺失角色 → 明确回复「该角色培养资料暂未收录」。

**验收**：
- 本地测试：`tests/test_nikke_meta.py` 覆盖已录入/未录入两条路径。
- 测试群实测：`/培养 红莲` → 四段式建议，末尾「按屑夫蒂一图流 XX 版」。
- 群内抽查 3~5 角色结论与一图流一致。

**回滚**：停用 `nikke_meta.py` 注册即可，P1/P2 不受影响。

## P4 日常更新（nikke_news）

**操作**：
1. 新建 `guild_war_bot/skills/nikke_news.py`：`/更新` `/公告` `/活动`。
2. 抓取 B 站官方动态（`space.bilibili.com/3546733590087876/dynamic`）与 TapTap 官方话题（`https://www.taptap.cn/app/737341/topic?type=official`）。
3. 归类：新卡池 / 新活动 / 新角色 / 系统改动 / 维护；输出最近相关 1~2 条 + 来源链接；缓存 1h。

**验收**：
- 本地测试：mock 动态列表接口，验证归类逻辑与缓存。
- 测试群实测：`/更新` → 最近更新条目 + 链接。
- 接口失败时回复「官方情报站暂时连接不上」，提供官方链接。

**回滚**：停用 `nikke_news.py` 注册。

## P5 前哨基地（nikke_outpost）

**操作**：
1. 新建 `guild_war_bot/skills/nikke_outpost.py`：`/基地 <普通进度> <困难进度>`。
2. 参数缺失 → 反问进度，或直接给计算器链接 `https://nikkeoutpost.netlify.app/`。
3. 二期：用 `nikke_campaign_stage_summary.json` 本地估算章节→等级映射，减少在线依赖。

**验收**：
- 本地测试：`tests/test_nikke_outpost.py` 覆盖有参/缺参/非法参数。
- 测试群实测：`/基地 16-14 8-5` → 基地等级与收益；`/基地` → 引导提供进度或给链接。

**回滚**：停用 `nikke_outpost.py` 注册。

## P6 回归加固

**操作**：
1. 全量测试：`cd F:\Codex\Nikke\Nikke_Bot && .venv\Scripts\python -m pytest`（或 `py -m pytest`）。
2. 更新 `Skills/README.md` 技能索引（新增 4 技能）。
3. 更新 AstrBot 插件 alias 与群内 `/帮助` 菜单。
4. 更新 `AGENTS.md`（新增 wiki_query 目录、新技能、数据源依赖）。
5. 缓存策略复查：内存 TTL + 磁盘缓存上限，防止长期运行内存膨胀。

**验收**：
- 全部测试通过；`/帮助` 显示新命令；正式群引入前在测试群连续运行 2 天无异常。

---

# 三、落地后（运维阶段）

## 3.1 日常巡检（建议每周一次）

```powershell
# 一键巡检脚本（可放入菜单 [5] 高级维护）
$checks = @(
  @{n="Ollama";   c={Invoke-RestMethod http://127.0.0.1:11434/api/tags}},
  @{n="桥接8793"; c={Invoke-RestMethod http://127.0.0.1:8793/health}},
  @{n="成员后台"; c={Invoke-RestMethod http://127.0.0.1:8788}}
)
foreach ($ch in $checks) {
  try { $ch.c() | Out-Null; Write-Host "$($ch.n): ok" -ForegroundColor Green }
  catch { Write-Host "$($ch.n): FAIL" -ForegroundColor Red }
}
```

巡检清单：
- [ ] 端口健康（11434 / 6185 / 6099 / 6199 / 8793 / 8788）
- [ ] QQ 小号仍在线（NapCat WebUI）
- [ ] 群内发一条 `/角色 红莲` 确认本地查询正常
- [ ] 数据文件是否过期（对比 `Nikke_Wiki/data` 更新时间）

## 3.2 数据更新流程

- **Nikke_Wiki 数据**：由 `Nikke_Wiki/scripts/` 现有脚本负责（`sync_nikke_wiki_assets.py`、`update_cn_release_status.py` 等），更新后**重启桥接服务**让索引重新加载。
- **角色培养库**：屑夫蒂一图流每次更新（通常每期卡池/活动后）→ 人工更新 `data/character_meta.json` 受影响角色 → 同步修改 `updated` 字段 → 群内公告「培养库已更新到 XX 版」。
- **黑话词典**：新黑话出现 → 补充 `laplace_system_prompt.md` 附录 A（或后续抽成独立 JSON）→ 重新粘贴 AstrBot 人格配置。

## 3.3 内容维护（双周）

- [ ] 检查 `/更新` 抓取是否正常（B 站/TapTap 接口可能变动，接口适配集中在一个模块便于修）
- [ ] 检查 `character_meta.json` 是否有角色缺录入（按群内提问热度补）
- [ ] 抽查缓存目录体积，清理过期缓存

## 3.4 排障手册（沿用 AGENTS.md 顺序，补充新链路）

机器人「没反应」时按序排查：

1. **Ollama**：`11434` 通？模型名正确？（改模型前先查 `/api/tags`，勿直接套旧模型名）
2. **AstrBot**：`6185` 通？人格配置生效？
3. **OneBot**：`6199` 监听？NapCat→AstrBot 有 Established WS？
4. **NapCat**：QQ 小号在线？WS 客户端地址为 `ws://127.0.0.1:6199/ws`？
5. **插件**：`astrbot_plugin_nikke_guild_bridge` 已启用？`bridge_url` 指向 `http://127.0.0.1:8793`？
6. **桥接**：`8793/health` ok？用 `/command` 本地 POST 测 `/角色 红莲`。
7. **新技能链路**：`wiki_query` 索引加载是否报错（看桥接日志）？数据文件是否被占用/损坏？
8. **群内触发**：是否 @ 到机器人？命令前缀是否符合唤醒规则？

新增注意点：
- 查询技能报错 → 先看桥接日志的 `wiki_query` 相关 traceback，**不要**第一时间怀疑 AstrBot。
- 在线抓取超时 → 看是否被风控（响应码 403/429），节流参数是否生效。

## 3.5 版本记录

每次变更在 `README_BOT_PROJECT.md` 或单独 CHANGELOG 记录：

```text
v1.1 (2026-08-11) 系统提示词：新增高频场景三件套（更新/基地/培养），修正"小伙子"为玩家爱称
v1.0 (2026-08-11) 系统提示词：拉普拉斯人格 + 会战命令 + 黑话词典
架构 v1.0 (2026-08-11) 落地方案：本地优先 + GameKee 兜底 + 4 技能
```

---

## 附录：常用命令速查

```powershell
# 启动日常
cd F:\Codex\Nikke\Nikke_Bot; .\start-nikke-qq-bot-menu.bat

# 桥接健康
Invoke-RestMethod http://127.0.0.1:8793/health

# 本地 POST 测命令
Invoke-RestMethod http://127.0.0.1:8793/command -Method Post -ContentType "application/json" -Body (@{
  text = "/角色 红莲"; sender_name = "测试"; sender_qq = "10001"
  is_admin = $false; session_id = "qq-group-test"
} | ConvertTo-Json -Compress)

# 数据源校验
cd F:\Codex\Nikke\Nikke_Wiki; py -c "import json,io; [json.load(io.open('data/'+f, encoding='utf-8')) for f in ['nikke_character_dictionary_enhanced.json','nikke_character_aliases.json','nikke_characters.json','cn_release_status.json']]; print('ok')"

# 全量测试
cd F:\Codex\Nikke\Nikke_Bot; py -m pytest

# Ollama 模型列表
Invoke-RestMethod http://127.0.0.1:11434/api/tags
```
