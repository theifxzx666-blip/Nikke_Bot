# -*- coding: utf-8 -*-
"""从 GameKee 在线抓取本地缺失角色，生成机器人侧补充词典 data/characters_extra.json。

补充词典结构兼容增强词典（name/cnName/class/burst/element/weapon/manufacturer/squad/rarity/
gamekeeContentId/skills/favoriteItem），skills 扩展支持 desc_lv10 珍藏品强化。
"""
from __future__ import annotations

import io
import json
from pathlib import Path

from guild_war_bot.wiki_query.online import _fetch_role_tree, _request_json

OUT = Path(r"F:\Codex\Nikke\Nikke_Bot\data\characters_extra.json")

# 本地缺失角色（GameKee 树里有，本地词典没有）
MISSING = [
    "麦斯威尔：平凡技师",
    "拉普拉斯：究极英雄",
    "玛律恰那：海洋进修",
    "灰姑娘：琉璃波光",
    "方舟黑色游侠",
    "舒恩",
    "谢芙蒂",
    "机甲谢芙蒂",
]

# 基本属性标签映射（标签 -> 词典字段）
PROFILE_MAP = {
    "企业": "manufacturer",
    "部队名称": "squad",
    "阶段": "burst",
    "属性": "element",
    "职业": "class",
    "武器": "weapon",
    "武器（名）": "weaponName",
    "稀有度": "rarity",
    "角色名称": "cnName",
}

# 企业/属性/职业 的中文映射（与增强词典 gamekee 中文字段对应）
COMPANY_CN = {"米西利斯": "米西利斯", "极乐净土": "极乐净土", "反常": "反常", "泰特拉": "泰特拉", "朝圣者": "朝圣者"}
ELEMENT_CN = {"风压": "风压", "燃烧": "燃烧", "水冷": "水冷", "电击": "电击", "铁甲": "铁甲"}
CLASS_CN = {"火力型": "火力型", "防御型": "防御型", "辅助型": "辅助型"}


def _extract_rows(content_id: int) -> list[list[dict]] | None:
    cdn = None
    detail = _request_json(f"https://www.gamekee.com/v1/content/detail/{content_id}")
    if detail and detail.get("code") == 0:
        try:
            cdn = detail["data"]["content_cdn"]
        except (KeyError, TypeError):
            cdn = None
    if not cdn:
        return None
    if cdn.startswith("//"):
        cdn = "https:" + cdn
    cdn = cdn.replace("https://api-cdn.gamekee.com/", "https://cdnimg-v2.gamekee.com/")
    payload = _request_json(cdn)
    if not payload:
        return None
    try:
        inner = json.loads(payload.get("content") or "{}")
        base = inner.get("baseData") or []
        return [row for row in base if isinstance(row, list)]
    except (json.JSONDecodeError, AttributeError):
        return None


def _label_values(rows: list[list[dict]]) -> dict[str, str]:
    out = {}
    for row in rows:
        cells = [c.get("value", "") for c in row if isinstance(c, dict)]
        if cells and cells[0]:
            out[cells[0]] = cells[1] if len(cells) > 1 else ""
    return out


def _parse_skills(rows: list[list[dict]]) -> dict:
    """解析技能块（含 desc_lv10 珍藏品强化）。"""
    labels = {}
    for i, row in enumerate(rows):
        cells = [c.get("value", "") for c in row if isinstance(c, dict)]
        if cells and cells[0]:
            labels[i] = cells[0]

    def parse_block(start: int, end: int, name_tag: str) -> dict | None:
        block_labels = {}
        for i in range(start, end):
            if i in labels:
                block_labels[labels[i]] = (
                    [c.get("value", "") for c in rows[i] if isinstance(c, dict)]
                    if isinstance(rows[i], list)
                    else []
                )
        name = block_labels.get(name_tag, [""])[1] if name_tag in block_labels else ""
        if not name:
            return None
        return {
            "name": name,
            "type": block_labels.get("技能类型", ["", ""])[1],
            "cooldown": block_labels.get("冷却时间", ["", ""])[1],
            "effect": block_labels.get("lv1", ["", ""])[1],
            "desc_lv10": block_labels.get("技能描述（lv10)）", ["", ""])[1],
        }

    # 找技能块边界（爆裂兼容「爆裂技能名称」与「爆裂技能」两种标签）
    starts = {}
    for i, tag in labels.items():
        if tag == "技能1名称":
            starts["技能1"] = i
        elif tag == "技能2名称":
            starts["技能2"] = i
        elif tag in ("爆裂技能名称", "爆裂技能"):
            starts["爆裂技能"] = i
    order = sorted(starts.items(), key=lambda x: x[1])
    skills = {}
    for idx, (tag, start) in enumerate(order):
        end = order[idx + 1][1] if idx + 1 < len(order) else len(rows)
        name_tag = "爆裂技能名称" if tag == "爆裂技能" else tag + "名称"
        # 兼容「爆裂技能名称」与「爆裂技能」两种标签
        if tag == "爆裂技能":
            name_tags = ("爆裂技能名称", "爆裂技能")
        else:
            name_tags = (name_tag,)
        parsed = None
        for nt in name_tags:
            parsed = parse_block(start, end, nt)
            if parsed and parsed["name"]:
                break
        if parsed and parsed["name"]:
            # 统一为增强词典的 key（skill1/skill2/burstSkill）
            key = {"技能1": "skill1", "技能2": "skill2", "爆裂技能": "burstSkill"}.get(tag, tag)
            skills[key] = parsed
    return skills


def build_character(role: dict) -> dict | None:
    cid = role.get("content_id")
    if not cid:
        return None
    rows = _extract_rows(cid)
    if not rows:
        return None
    vals = _label_values(rows)

    name = str(role.get("name") or vals.get("角色名称") or "").strip()
    if not name:
        return None

    rec = {
        "name": name,
        "cnName": name,
        "aliases": name,
        "gamekeeContentId": cid,
        "gamekeeCnName": name,
        "skills": _parse_skills(rows),
        "favoriteItem": {"status": "待确认", "itemName": "", "note": "补充词典角色"},
    }
    # 基本属性
    for tag, field in PROFILE_MAP.items():
        value = str(vals.get(tag) or "").strip()
        if value and field not in ("cnName",):
            rec[field] = value
    # 中文冗余字段（与增强词典对齐，供 summarize 使用）
    if rec.get("manufacturer"):
        rec["gamekeeCompanyCn"] = rec["manufacturer"]
    if rec.get("element"):
        rec["gamekeeElementCn"] = rec["element"]
    if rec.get("class"):
        rec["gamekeeClassCn"] = rec["class"]
    if rec.get("weapon"):
        rec["gamekeeWeaponCn"] = rec["weapon"]
    if rec.get("burst"):
        rec["gamekeeStageCn"] = rec["burst"]
    if rec.get("rarity"):
        rec["gamekeeRarityCn"] = rec["rarity"]
    # 珍藏品（缓存探测）
    if vals.get("珍藏品名称"):
        rec["favoriteItem"] = {
            "status": "已确认",
            "itemName": vals.get("珍藏品名称", ""),
            "rarity": vals.get("珍藏品稀有度", ""),
            "desc": vals.get("珍藏品简介", ""),
        }
    return rec


def main() -> None:
    roles = _fetch_role_tree()
    if not roles:
        print("目录树获取失败")
        return
    by_name = {str(r.get("name") or "").strip(): r for r in roles}
    result = []
    for missing in MISSING:
        role = by_name.get(missing)
        if not role:
            print(f"❌ 树中未找到: {missing}")
            continue
        rec = build_character(role)
        if rec:
            result.append(rec)
            skill_ok = bool(rec.get("skills"))
            print(f"✅ {missing}: 技能={skill_ok} 珍藏品={rec['favoriteItem'].get('status')}")
        else:
            print(f"⚠️ {missing}: 详情抓取失败")
    with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print(f"\n共写入 {len(result)} 个角色 -> {OUT}")


if __name__ == "__main__":
    main()
