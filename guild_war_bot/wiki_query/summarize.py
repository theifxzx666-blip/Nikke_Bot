# -*- coding: utf-8 -*-
"""角色卡摘要生成。

P1 阶段输出文本角色卡（中文优先，gamekee 中文缺失时回退英文字段）。
立绘图片由技能层通过 ReplyPort.send_image 发送。
"""

from __future__ import annotations

from typing import Any

from .index import WikiIndex

# 部队中文名映射（只收录常用/会战相关部队，未收录的原样展示）
_SQUAD_CN: dict[str, str] = {
    "Pioneer": "开拓者",
    "Counters": "反击者",
    "Matis": "墨提斯",
    "Absolute": "绝对",
    "Goddess": "女神",
    "Inherit": "传承",
    "Heretic": "异端者",
    "Exotic": "异端/外域",
    "Extrinsic": "外因者",
    "Underworld Queen": "地下女王",
    "Aegis": "埃癸斯",
    "Seraphim": "炽天使",
    "Talentum": "天启",
    "Mighty Tools": "强力工具",
    "777": "777",
    "M.M.R.": "MMR",
    "A.C.P.U.": "ACPU",
    "B.S.T.": "BST",
    "Cafe Sweety": "甜心咖啡",
    "Café LycoReco": "咖啡厅LycoReco",
    "Maid For You": "为你女仆",
    "Happy Zoo": "快乐动物园",
    "Wardress": "典狱官",
    "Master Hand": "大师之手",
    "School Circle": "校园圈",
    "Prima Donna": "首席歌姬",
    "Dazzling Pearl": "璀璨珍珠",
    "White Knight": "白骑士",
    "Real Kindness": "真心",
    "Perilous Siege": "危城",
    "Heavy Gram": "重炮",
    "Incubator": "孵化器",
    "Infinity Rail": "无限轨道",
    "Electric Shock": "电击",
    "Triangle": "三角",
    "Nepenthe": "忘忧",
    "Best Seller": "畅销",
    "Protocol": "协议",
    "Overseer": "监督者",
    "Recall & Release": "召回与释放",
    "Rewind": "倒带",
    "Replace": "替代",
    "Old Tales": "旧闻",
    "Veiled Order": "蒙面团",
    "YoRHa": "寄叶",
    "WILLE": "WILLE",
    "NERV": "NERV",
}


def _squad_cn(squad: str) -> str:
    return _SQUAD_CN.get(squad, squad)


_CARD_FIELD_MAP: tuple[tuple[str, str, str], ...] = (
    ("gamekeeClassCn", "class", "职业"),
    ("gamekeeStageCn", "burst", "爆裂"),
    ("gamekeeElementCn", "element", "元素"),
    ("gamekeeWeaponCn", "weapon", "武器"),
    ("gamekeeCompanyCn", "manufacturer", "阵营"),
    ("gamekeeRarityCn", "rarity", "稀有度"),
)


def summarize_character(index: WikiIndex, rec: dict[str, Any]) -> str:
    """由角色记录生成群内角色卡文本（中文优先，缺失回退英文）。"""
    name = str(rec.get("cnName") or rec.get("name") or "未知角色")
    squad = str(rec.get("squad") or "").strip()
    released = str(rec.get("cnReleased") or "").strip()

    lines = [f"名称：{name}"]
    for cn_field, en_field, label in _CARD_FIELD_MAP:
        value = str(rec.get(cn_field) or rec.get(en_field) or "").strip()
        if value:
            lines.append(f"{label}：{value}")
    if squad:
        lines.append(f"部队：{_squad_cn(squad)}")
    if released:
        lines.append(f"国服：{released}")

    return "\n".join(lines)


def character_portrait_path(rec: dict[str, Any]) -> str | None:
    """返回本地立绘路径（存在才返回，否则 None）。

    优先级：PNG 队伍卡/立绘 > webp 立绘 > 图标，降低格式兼容风险。
    """
    candidates = [
        str(rec.get("gamekeeLocalTeamCardFile") or "").strip(),
        str(rec.get("localPortraitFile") or "").strip(),
        str(rec.get("localIconFile") or "").strip(),
    ]
    for path in candidates:
        if path and path.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            return path
    return None


def not_found_text(query: str) -> str:
    """未命中时的友好提示（不编造）。"""
    return f"角色「{query}」暂时没查到资料，指挥官再核对一下名字？也可以试试 /wiki <关键词> 在线查询。"
