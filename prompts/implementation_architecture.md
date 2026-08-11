# 拉普拉斯机器人 · 落地方案架构设计（v1.0）

> 关联：`prompts/laplace_system_prompt.md`（系统提示词 v1.1）
> 本地数据源：`F:\Codex\Nikke\Nikke_Wiki`　在线数据源：`https://www.gamekee.com/nikke/`
> 日期：2026-08-11

---

## 0. 设计目标与原则

1. **本地优先，在线兜底**：191 个角色 × 46 字段的增强词典已在本机，绝大多数角色查询本地即可秒回；GameKee 只用于本地缺失字段与内容详情的在线兜底。
2. **不把逻辑写进 AstrBot 插件**：AstrBot 插件保持纯桥接（转发 + 回传），业务逻辑全部落在 `guild_war_bot/skills/` 技能层，延续现有 `SkillRegistry` 机制。
3. **黑话统一入口**：所有查询先过别名归一化，避免「红莲 / 无头 / 剑圣」这类称呼导致检索失败。
4. **可离线可观测**：缓存命中率、抓取失败、来源标注都要可追踪；离线时优雅降级（明确说查不到，不编造）。
5. **同步 prompt 附录**：本方案中的技能清单与 `laplace_system_prompt.md` 附录 B 一一对应，改一边必须同步另一边。

---

## 1. 总体架构

```text
┌────────────────────────── QQ 群 ──────────────────────────┐
│  群友 @机器人 / /命令                                        │
└────────────────────────────┬─────────────────────────────┘
                             ▼
┌────────────────────── NapCat（QQ 小号）───────────────────┐
│  消息接入 + 回复发送（OneBot v11）                          │
└────────────────────────────┬─────────────────────────────┘
                             ▼ 反向 WebSocket :6199/ws
┌────────────────────── AstrBot（人格层）───────────────────┐
│  · 拉普拉斯系统提示词（laplace_system_prompt.md）            │
│  · 唤醒规则（@ / 前缀）→ 识别为"会战命令"还是"问答"          │
│  · 插件 astrbot_plugin_nikke_guild_bridge（纯桥接）         │
└────────────────────────────┬─────────────────────────────┘
                             ▼ HTTP :8793/command
┌────────────── 本地桥接服务 guild_war_bot.service_http ─────┐
│  路由：/命令 → SkillRegistry → 对应技能                      │
│        /问答 → WikiQueryService → 检索流水线                 │
└───────┬──────────────────────────────┬────────────────────┘
        ▼                              ▼
┌─ 技能层 guild_war_bot/skills/ ──┐  ┌─ 检索流水线 WikiQuery ─┐
│ 会战技能（已有 9 个，不动）        │  │ 1 别名归一化            │
│ 新增：                           │  │ 2 本地索引命中          │
│ · nikke_wiki.py                 │  │ 3 在线兜底 GameKee     │
│ · nikke_meta.py                 │  │ 4 内容清洗/摘要          │
│ · nikke_news.py                 │  │ 5 缓存 & 来源标注        │
│ · nikke_outpost.py              │  └───────────┬────────────┘
└───────┬──────────────────────────┘              ▼
        ▼                                 ┌─ 数据层 ─┐
┌─ 存储/业务 ─┐                            │ 本地 JSON │
│ guild_war.db │                           │ Nikke_Wiki│
│ (会战记录)   │                           │ 缓存/导出  │
└─────────────┘                           └───────────┘
```

### 分层职责

| 层 | 组件 | 职责 | 归属 |
| --- | --- | --- | --- |
| 消息接入 | NapCat | 登录 QQ、收发群消息 | 已有 |
| 人格调度 | AstrBot | 系统提示词、唤醒规则、LLM 调用 | 已有 |
| 桥接 | AstrBot 插件 | 命令/问答转发到本地 HTTP，回传结果 | 已有 |
| 路由 | `service_http.py` | `/command` 分发：会战 vs 问答 | 已有（小扩展） |
| 技能层 | `guild_war_bot/skills/` | 业务技能：会战 + 新增 4 个查询技能 | 新增 |
| 检索层 | `wiki_query/` | 别名归一化、本地索引、在线兜底、清洗摘要 | 新增 |
| 数据层 | `F:\Codex\Nikke\Nikke_Wiki\data` | 角色词典、别名、国服状态、GameKee 缓存 | 已有 |

---

## 2. 数据层设计（本地 Wiki 接入）

### 2.1 本地数据源清单（只读引用，不复制）

| 文件 | 内容 | 用途 | 大小 |
| --- | --- | --- | --- |
| `data/nikke_character_dictionary_enhanced.json` | 191 角色 × 46 字段（cnName/aliases/manufacturer/squad/class/burst/rarity/weapon/element/cnReleased/gamekeeEntryId/gamekeeContentId/本地图标路径…） | **主数据源**，角色卡查询 | ~614KB |
| `data/nikke_character_aliases.json` | 190 个角色别名映射（name → [别名列表]） | 黑话/昵称归一化 | ~9KB |
| `data/nikke_characters.json` | 190 角色基础属性表 | 快速属性索引 | ~38KB |
| `data/cn_release_status.json` | 128 角色国服上线状态（status/date/basis） | 抽卡建议依据（是否已上线国服） | ~21KB |
| `data/nikke_campaign_stage_summary.json` | 关卡概要 | 前哨基地进度换算（二期） | ~932KB |
| `cache/gamekee_content_details/*.json` | GameKee 内容详情页缓存（含角色正文） | 在线内容的本地缓存层 | 各 ~150-240KB |

### 2.2 索引方案（启动时一次性加载进内存）

```python
# wiki_query/index.py 概念设计
class WikiIndex:
    """启动时加载本地 JSON，构建三张内存索引，全量 <10MB，毫秒级命中"""
    def __init__(self, data_dir):
        self.characters = load_json(data_dir / "nikke_character_dictionary_enhanced.json")  # list[dict]
        self.by_name   = {c["name"]: c for c in self.characters}      # 英文名索引
        self.by_cnname = {c["cnName"]: c for c in self.characters}    # 中文名索引
        self.by_alias  = build_alias_index(load_json(data_dir / "nikke_character_aliases.json"))
        self.cn_status = load_json(data_dir / "cn_release_status.json")
        # by_alias 结构：{别名: 正式角色名}，查询时先归一化再查 by_name/by_cnname
```

要点：
- **只读**：`Nikke_Wiki/data` 是上游数据仓库，机器人侧只 `open()` 读取，绝不写入。数据更新由 `Nikke_Wiki/scripts/` 现有脚本负责，机器人启动时自动加载最新版。
- 数据源路径做成配置项（`data/wiki_data_dir`），默认指向 `F:\Codex\Nikke\Nikke_Wiki\data`，可被环境变量覆盖。
- 加载失败/文件缺失 → 降级为「仅在线查询」模式并在日志标记，不崩溃。

### 2.3 在线兜底：GameKee

- 入口：`https://www.gamekee.com/nikke/`
- 已有资产可复用：`gamekee_entry_bind_data.json`（条目绑定映射）、`gamekee_api_tree_64581.json`、`cache/` 中的 HTML/JS/内容详情。
- 抓取策略：
  1. 先用 `gamekeeEntryId` / `gamekeeContentId`（已在增强词典中）直接拼内容详情 URL，优先于全文搜索。
  2. 命中缓存 `cache/gamekee_content_details/content_<id>.json` 直接读，不重复抓取。
  3. 未命中 → 请求在线内容页 → 落缓存 → 清洗正文。
- 在线请求必须：`requests` + 超时（默认 8s）+ UA + 失败重试 1 次 + 全局节流（间隔 ≥1s），避免被风控。
- 内容清洗：剥离 HTML 标签/脚本/广告，只保留正文段落；**输出 ≤4 句转述 + 来源链接**。

---

## 3. 技能层设计（新增 4 个技能 + 通用检索服务）

### 3.1 通用检索服务 `wiki_query/`（新目录，被各技能复用）

```text
guild_war_bot/
  wiki_query/
    __init__.py
    index.py          # WikiIndex：本地三索引加载与查询
    normalizer.py     # 黑话/别名归一化（对齐 prompt 附录 A）
    gamekee.py        # GameKee 在线兜底：URL 拼接、抓取、清洗、缓存
    summarize.py      # 摘要生成：字段挑选 + 短文本转述（≤4 句）
    cache.py          # TTL 缓存（内存 dict + 可选磁盘 json）
```

查询流水线（所有查询技能共用）：

```text
输入查询串
   → normalizer.normalize(q)        # 黑话→正式名（附录A + aliases.json）
   → 问题分类（角色培养/机制/活动/数值…）
   → index.lookup(name)             # 本地命中？
        ├─ 是 → summarize.local(record) → 回复 + 来源「本地角色资料库」
        └─ 否 → gamekee.fetch(entry_id)  → 清洗 → summarize.web(content)
                → cache.put(key, result) → 回复 + 来源「GameKee」
```

### 3.2 技能清单

| 技能文件 | 群命令 | 对应 prompt 场景 | 数据流 |
| --- | --- | --- | --- |
| `skills/nikke_wiki.py` | `/角色 <名>`、`/wiki <词>` | 通用游戏答疑 | 本地索引 → GameKee 兜底 |
| `skills/nikke_meta.py` | `/培养 <名>`、`/抽卡 <名>` | 场景 3 角色培养 | 本地基础数据 + 屑夫蒂一图流（见 3.3） |
| `skills/nikke_news.py` | `/更新`、`/公告`、`/活动` | 场景 1 日常更新 | 官方 B 站动态 + TapTap（抓取） |
| `skills/nikke_outpost.py` | `/基地 <普通> <困难>` | 场景 2 前哨基地 | nikkeoutpost 计算器 + 本地关卡表 |

### 3.3 `nikke-meta`（角色培养建议）实现要点

- 数据分层：
  1. **硬数据**（本地，可靠）：角色属性、职业、爆裂阶、国服是否上线 → 直接来自增强词典。
  2. **推荐数据**（人工维护，权威）：抽卡评级 / 词条优先级 / 珍藏品 / 加点方案 → 维护为 `data/character_meta.json`（人工从屑夫蒂一图流录入，见下方数据结构）。
  3. **在线兜底**：本地没有该角色 meta → 抓取屑夫蒂一图流 opus 页/最新动态，OCR 或人工摘要后入缓存。
- `data/character_meta.json` 建议结构：

```json
{
  "红莲": {
    "pull": {"verdict": "推荐", "note": "朝圣者高泛用火力，会战推图双修"},
    "t10": {"priority": 1, "note": "头手必做"},
    "rolls": {"priority": ["攻刃", "暴击", "充能"], "note": "3 词条建议 2攻1暴"},
    "treasure": {"do": false, "note": "珍藏品收益一般，可后置"},
    "skills": {
      "transition": "4/4/10",       // 过渡加点：资源有限时先点满 B3
      "final": "10/10/10"           // 终极加点
    },
    "source": "屑夫蒂一图流 2026-08 版",
    "updated": "2026-08-11"
  }
}
```

- 输出模板（对齐 prompt 场景 3 的四段结构）：

```text
【红莲·培养建议】(来源：屑夫蒂一图流)
1. 抽卡：推荐。朝圣者高泛用火力，会战推图双修。
2. T10：头手必做（优先级1）。词条：攻刃 > 暴击 > 充能。
3. 珍藏品：收益一般，可后置。
4. 加点：过渡 4/4/10，终极 10/10/10。
```

### 3.4 `nikke-news`（日常更新）实现要点

- 两个数据源抓取（B 站动态、TapTap 官方话题），均走异步 + 超时 + 失败回退。
- B 站动态：`space.bilibili.com/3546733590087876/dynamic` → 解析动态列表 API（`/wbi/nav` + dynamic 列表接口，或直接抓页面），提取最新 5 条标题+发布时间。
- 归类规则：标题/正文含「卡池/UP/招募」→ 新卡池；「活动」→ 新活动；「维护/更新」→ 系统改动。
- 输出：`最近更新（来源：官方B站动态）：\n▶ 08-10 新卡池「XXX」上线\n▶ 08-09 活动「XXX」开启`，附来源链接。
- 缓存 1h；失败回复「官方情报站暂时连接不上，指挥官稍后再试」。

### 3.5 `nikke-outpost`（前哨基地）实现要点

- 输入校验：必须拿到「普通主线进度 + 困难主线进度」，缺任一 → 反问，或直接给计算器链接 `https://nikkeoutpost.netlify.app/`。
- 二期增强：用 `nikke_campaign_stage_summary.json` 本地估算（若该表含章节→等级映射），减少对在线计算器的依赖。

---

## 4. 路由与桥接扩展

### 4.1 `service_http.py` 分发扩展

```text
POST /command 请求体: {text, sender_name, sender_qq, is_admin, session_id}
  → 若 text 以 "/" 开头 → SkillRegistry 路由（会战技能 + 新增查询技能）
  → 若 text 是自然语言问答（AstrBot 已按唤醒规则转发）→ WikiQueryService.answer()
```

### 4.2 AstrBot 插件侧（保持最小改动）

- 新增 4 个命令 alias：`/角色`、`/培养`、`/更新`、`/基地`（在插件 `_conf_schema.json` / alias 配置中登记，指向同一 `/command` 端点）。
- 自然语言问答仍走 AstrBot 的 LLM 人格层：LLM 判断「需要查 Wiki」时，生成 `/角色 xxx` 或 `/wiki xxx` 形式命令转发给桥接，或由插件配置「工具调用」映射。
- 图片回传：异步技能（新闻/一图流）产出图片时，复用现有 outbox 轮询机制。

---

## 5. 分阶段落地路线

| 阶段 | 内容 | 验收标准 |
| --- | --- | --- |
| **P1 本地角色查询** | `wiki_query/` 索引 + `nikke_wiki.py` 技能 | 群内 `/角色 红莲` 秒回角色卡（职业/爆裂/元素/国服状态/头像） |
| **P2 在线兜底** | `gamekee.py` 抓取 + 缓存 + 清洗 | `/角色 <本地没有的角色>` 走 GameKee 返回 ≤4 句摘要 + 来源 |
| **P3 培养建议** | `character_meta.json`（先录入 Top20 热门角色）+ `nikke_meta.py` | `/培养 红莲` 输出四段式建议，注明来源 |
| **P4 日常更新** | `nikke_news.py` 接 B 站 + TapTap | `/更新` 返回最近 1~2 条归类更新 + 链接 |
| **P5 前哨基地** | `nikke_outpost.py` 接计算器/本地关卡表 | `/基地 16-14 8-5` 返回基地等级与收益 |
| **P6 回归加固** | tests 覆盖全部新技能 + 缓存策略 + 降级路径 | `pytest` 全绿；断网时机器人明确说查不到而非编造 |

建议 P1 必须完成后再进 P2；P3 的人工录入是性价比最高的投入（一图流是图片，OCR 不如人工录入稳定）。

---

## 6. 目录变更清单（落地时新增）

```text
F:\Codex\Nikke\Nikke_Bot\
  guild_war_bot\
    wiki_query\                 # 新增：通用检索服务
      __init__.py
      index.py                  # WikiIndex 本地三索引
      normalizer.py             # 黑话/别名归一化
      gamekee.py                # GameKee 在线兜底
      summarize.py              # 摘要生成
      cache.py                  # TTL 缓存
    skills\
      nikke_wiki.py             # 新增：/角色 /wiki
      nikke_meta.py             # 新增：/培养 /抽卡
      nikke_news.py             # 新增：/更新 /公告 /活动
      nikke_outpost.py          # 新增：/基地
      registry.py               # 修改：注册 4 个新技能
  data\
    character_meta.json         # 新增：培养建议人工库（P3）
  tests\
    test_wiki_query.py          # 新增：索引/归一化/缓存测试
    test_nikke_meta.py          # 新增
    test_nikke_news.py          # 新增
  prompts\
    laplace_system_prompt.md    # 已更新 v1.1（附录B 技能清单与本方案对齐）
    implementation_architecture.md  # 本文档
```

---

## 7. 风险与边界

| 风险 | 缓解 |
| --- | --- |
| GameKee 在线抓取被风控/结构变化 | 本地优先；缓存降级；`inspect_gamekee_api.py` 可复用核对 API 结构 |
| 一图流为图片、OCR 不稳定 | 人工录入 `character_meta.json` 为主，OCR 仅作辅助 |
| B 站/TapTap 动态接口变动 | 抓取失败降级为「暂不可查」+ 提供官方链接；接口适配集中在一个模块 |
| 数据文件体积大（icon_index 9.9MB 等） | 只加载必要文件；大文件做懒加载或只读不载入内存 |
| 与现有会战体系冲突 | 新技能走同一 SkillRegistry，AstrBot 插件零膨胀；先测试群后正式群 |
| 敏感信息 | 不把 QQ token / GameKee 账号写入仓库；`character_meta.json` 仅放公开攻略结论 |
