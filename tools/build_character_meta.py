# -*- coding: utf-8 -*-
"""屑夫蒂一图流 → character_meta.json 结构化提取 v2
策略：角色名（词典匹配）作锚点 → 向上找同列字段（装备/词条/技能/魔方/收藏品/珍藏品/备注）
"""
import json
import os
import re
from collections import defaultdict

from guild_war_bot.wiki_query import default_index

BLOCKS = r"F:\Codex\Nikke\Nikke_Bot\data\_ocr_full\all_blocks.json"
META_OUT = r"F:\Codex\Nikke\Nikke_Bot\data\character_meta.json"

# 字段前缀（OCR 可能误读，做包含匹配）
FIELD_PATTERNS = [
    ("装备", "装备"),
    ("词条", "词条"),
    ("技能", "技能"),
    ("魔方", "魔方"),
    ("收藏品", "收藏品"),
    ("珍藏品", "珍藏品"),
    ("备注", None),  # 无前缀的独立文本
]


def load_blocks():
    with open(BLOCKS, encoding="utf-8") as f:
        return json.load(f)


def build_name_map():
    idx = default_index()
    name_map = {}
    for rec in idx.characters:
        cn = str(rec.get("cnName") or "").strip()
        if cn:
            name_map[cn] = cn
    extra = os.path.join(r"F:\Codex\Nikke\Nikke_Bot\data", "characters_extra.json")
    if os.path.exists(extra):
        with open(extra, encoding="utf-8") as f:
            for rec in json.load(f):
                cn = str(rec.get("cnName") or "").strip()
                if cn:
                    name_map[cn] = cn
    return name_map


def dedup(blocks):
    """按位置去重（重叠块保留 score 高的）"""
    out = []
    for b in blocks:
        x0, y0, x1, y1 = b["box"]
        dup = False
        for o in out:
            ox0, oy0, ox1, oy1 = o["box"]
            # 中心距离 < 25px 视为重复
            if abs((x0 + x1) / 2 - (ox0 + ox1) / 2) < 25 and abs((y0 + y1) / 2 - (oy0 + oy1) / 2) < 25:
                dup = True
                break
        if not dup:
            out.append(b)
    return out


def merge_split_values(blocks):
    """合并 '标签：'（无值）与紧随的数值块：技能： + 7+/4+/7+"""
    result = list(blocks)
    for i, b in enumerate(blocks):
        t = b["text"].strip()
        if not (t.startswith("技能：") or t.startswith("技能:")) or len(t) > 6:
            continue
        # 无值：找 y 略下方且 x 相近的数值块
        x0, y0, x1, y1 = b["box"]
        for ob in blocks:
            ox0, oy0, ox1, oy1 = ob["box"]
            ot = ob["text"].strip()
            if not ot or ot.startswith(("技能", "装备", "词条", "魔方", "收藏品", "珍藏品")):
                continue
            # 数值块特征：短文本含数字/+/-，或纯文本
            if re.match(r"^[\d/+\-A-Za-z（()）+．.、]+$", ot):
                if abs((ox0 + ox1) / 2 - (x0 + x1) / 2) < 300 and 0 < oy0 - y0 < 60:
                    # 标签可能被 OCR 截断（如 "技能：1"），只保留标签部分 + 完整值
                    label = t.split("：")[0] if "：" in t else t.split(":")[0]
                    merged = {"text": f"{label}：{ot}", "box": b["box"]}
                    result.append(merged)
                    break
    return result


def main():
    blocks = dedup(load_blocks())
    blocks = merge_split_values(blocks)
    name_map = build_name_map()
    print(f"去重后文本块: {len(blocks)}")

    # 1. 找角色名锚点
    anchors = []
    for b in blocks:
        t = b["text"].strip()
        if t in name_map:
            anchors.append((b, name_map[t]))
    print(f"角色名锚点: {len(anchors)}")

    # 2. 每个锚点向上找字段
    records = {}
    for b, formal in anchors:
        cx = (b["box"][0] + b["box"][2]) / 2
        cy = (b["box"][1] + b["box"][3]) / 2
        fields = {"name": formal, "note": ""}
        # 找同列（x 差 < 320）且在名字上方 450px 内的块
        for ob in blocks:
            ox = (ob["box"][0] + ob["box"][2]) / 2
            oy = (ob["box"][1] + ob["box"][3]) / 2
            if abs(ox - cx) > 320 or not (cy - 450 < oy < cy):
                continue
            text = ob["text"].strip()
            if text == formal or text in name_map:
                continue  # 跳过其他角色名
            matched = False
            for key, _ in FIELD_PATTERNS:
                if text.startswith(key + "：") or text.startswith(key + ":"):
                    value = text[len(key) + 1:].strip()
                    if key == "装备":
                        fields["gear"] = value
                    elif key == "词条":
                        fields["gear_stat"] = value
                    elif key == "技能":
                        fields["skill"] = value
                    elif key == "魔方":
                        fields["cube"] = value
                    elif key in ("收藏品", "珍藏品"):
                        fields["collection"] = value
                    matched = True
                    break
            if not matched and text and not any(k in text for k in ["装备", "词条", "技能", "魔方", "收藏品", "珍藏品"]):
                # 备注候选（无标签的说明文字）
                if "：" not in text and ":" not in text and len(text) < 30 and not re.match(r"^[\d/+\-]+$", text):
                    if not fields["note"]:
                        fields["note"] = text
        records[formal] = fields

    # 3. 输出
    print(f"\n提取到角色卡: {len(records)}")
    for name, fields in sorted(records.items()):
        print(f"\n【{name}】")
        for k, v in fields.items():
            if k != "name" and v:
                print(f"  {k}: {v}")

    # 4. 写入 character_meta.json（合并已有）
    meta = {}
    if os.path.exists(META_OUT):
        with open(META_OUT, encoding="utf-8") as f:
            meta = json.load(f)
    for name, fields in records.items():
        # 去掉空字段
        clean = {k: v for k, v in fields.items() if v}
        meta[name] = clean
    with open(META_OUT, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    print(f"\n已写入 {META_OUT}: {len(meta)} 个角色")


if __name__ == "__main__":
    main()
