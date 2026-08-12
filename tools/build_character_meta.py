# -*- coding: utf-8 -*-
"""屑夫蒂一图流 → character_meta.json + 角色区块截图 全流程工具。

用法：
    PYTHONPATH=F:/Codex/Nikke/Nikke_Bot .venv/Scripts/python.exe tools/build_character_meta.py

流程：
    1. 分块 OCR 屑夫蒂一图流（RapidOCR，本地离线）
    2. 角色名（词典）锚点 + 向上提取 装备/词条/技能/魔方/收藏品/备注
    3. 裁剪每个角色的原图区块（立绘+养成方案）→ data/meta_crops/<角色名>.png
    4. 写入 data/character_meta.json

依赖：pip install rapidocr-onnxruntime（见 requirements-local.txt）
"""
import json
import os
import re
from collections import defaultdict

from PIL import Image

from guild_war_bot.wiki_query import default_index

SRC = r"F:\Codex\Nikke\Nikke_Wiki\kol\260725_屑夫蒂_养成一图流_国服.png"
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
META_OUT = os.path.join(DATA_DIR, "character_meta.json")
CROPS_DIR = os.path.join(DATA_DIR, "meta_crops")
WORK_DIR = os.path.join(DATA_DIR, "_ocr_work")

CHUNK_H = 2100   # 分块高度
OVERLAP = 120    # 块重叠
SCALE = 1.5      # OCR 放大倍率
CROP_UP = 720    # 角色区块向上延伸（立绘+字段）
CROP_HALF_W = 400  # 区块横向半宽

FIELD_LABELS = ["装备", "词条", "技能", "魔方", "收藏品", "珍藏品", "强度", "强度评级"]


def ocr_full_image() -> list[dict]:
    """分块 OCR 整图，返回带原图坐标的文本块列表。"""
    from rapidocr_onnxruntime import RapidOCR

    os.makedirs(WORK_DIR, exist_ok=True)
    img = Image.open(SRC).convert("RGB")
    W, H = img.size
    print(f"原图: {W}x{H}")
    engine = RapidOCR()
    all_blocks = []
    y, idx = 0, 0
    while y < H:
        y2 = min(y + CHUNK_H, H)
        crop = img.crop((0, y, W, y2))
        w, h = crop.size
        crop = crop.resize((int(w * SCALE), int(h * SCALE)), Image.LANCZOS)
        tmp = os.path.join(WORK_DIR, f"_chunk{idx}.png")
        crop.save(tmp, "PNG")
        result, _ = engine(tmp)
        for box, text, score in result or []:
            if not text.strip():
                continue
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            all_blocks.append({
                "text": text.strip(),
                "score": round(float(score), 4),
                "box": [round(min(xs) / SCALE, 1), round(y + min(ys) / SCALE, 1),
                        round(max(xs) / SCALE, 1), round(y + max(ys) / SCALE, 1)],
            })
        print(f"[块{idx}] y={y}-{y2}, 文本块 {len(result) or 0}")
        idx += 1
        if y2 >= H:
            break
        y = y2 - OVERLAP
    with open(os.path.join(WORK_DIR, "all_blocks.json"), "w", encoding="utf-8") as f:
        json.dump(all_blocks, f, ensure_ascii=False, indent=1)
    print(f"OCR 完成，共 {len(all_blocks)} 文本块")
    return all_blocks


def dedup(blocks):
    out = []
    for b in blocks:
        x0, y0, x1, y1 = b["box"]
        dup = False
        for o in out:
            ox0, oy0, ox1, oy1 = o["box"]
            if abs((x0 + x1) / 2 - (ox0 + ox1) / 2) < 25 and abs((y0 + y1) / 2 - (oy0 + oy1) / 2) < 25:
                dup = True
                break
        if not dup:
            out.append(b)
    return out


def merge_split_values(blocks):
    """合并 '技能：'（无值/截断）与紧随的数值块"""
    result = list(blocks)
    for b in blocks:
        t = b["text"].strip()
        if not (t.startswith("技能：") or t.startswith("技能:")) or len(t) > 6:
            continue
        x0, y0, x1, y1 = b["box"]
        for ob in blocks:
            ox0, oy0, ox1, oy1 = ob["box"]
            ot = ob["text"].strip()
            if not ot or ot.startswith(("技能", "装备", "词条", "魔方", "收藏品", "珍藏品")):
                continue
            if re.match(r"^[\d/+\-A-Za-z（()）+．.、]+$", ot):
                if abs((ox0 + ox1) / 2 - (x0 + x1) / 2) < 300 and 0 < oy0 - y0 < 60:
                    label = t.split("：")[0] if "：" in t else t.split(":")[0]
                    result.append({"text": f"{label}：{ot}", "box": b["box"]})
                    break
    return result


def build_name_map():
    idx = default_index()
    name_map = {}
    for rec in idx.characters:
        cn = str(rec.get("cnName") or "").strip()
        if cn:
            name_map[cn] = cn
    extra = os.path.join(DATA_DIR, "characters_extra.json")
    if os.path.exists(extra):
        with open(extra, encoding="utf-8") as f:
            for rec in json.load(f):
                cn = str(rec.get("cnName") or "").strip()
                if cn:
                    name_map[cn] = cn
    return name_map


def extract(blocks, name_map):
    """角色名锚点 + 字段提取，返回 {正式名: {字段..., 'anchor_box': [...]}}"""
    records = {}
    for b in blocks:
        t = b["text"].strip()
        if t not in name_map:
            continue
        formal = name_map[t]
        cx = (b["box"][0] + b["box"][2]) / 2
        cy = (b["box"][1] + b["box"][3]) / 2
        fields = {"name": formal, "note": "", "anchor_box": b["box"]}
        for ob in blocks:
            ox = (ob["box"][0] + ob["box"][2]) / 2
            oy = (ob["box"][1] + ob["box"][3]) / 2
            if abs(ox - cx) > 320 or not (cy - 450 < oy < cy):
                continue
            text = ob["text"].strip()
            if text == formal or text in name_map:
                continue
            matched = False
            for key in FIELD_LABELS:
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
                    elif key in ("强度", "强度评级"):
                        fields["strength"] = value
                    matched = True
                    break
            if not matched and text and not any(k in text for k in FIELD_LABELS):
                if "：" not in text and ":" not in text and len(text) < 30 \
                        and not re.match(r"^[\d/+\-]+$", text):
                    if not fields["note"]:
                        fields["note"] = text
        records[formal] = fields
    return records


def export_crops(records):
    """裁剪每个角色的原图区块（立绘+养成方案）"""
    os.makedirs(CROPS_DIR, exist_ok=True)
    img = Image.open(SRC).convert("RGB")
    W, H = img.size
    count = 0
    for formal, fields in records.items():
        x0, y0, x1, y1 = fields["anchor_box"]
        cy = (y0 + y1) / 2
        cx = (x0 + x1) / 2
        top = max(0, int(cy - CROP_UP))
        bottom = min(H, int(cy + 40))
        left = max(0, int(cx - CROP_HALF_W))
        right = min(W, int(cx + CROP_HALF_W))
        crop = img.crop((left, top, right, bottom))
        # 放大 1.5x 便于查看
        w, h = crop.size
        crop = crop.resize((int(w * 1.5), int(h * 1.5)), Image.LANCZOS)
        # 文件名：去冒号等非法字符
        safe = re.sub(r'[\\/:*?"<>|]', "", formal)
        path = os.path.join(CROPS_DIR, f"{safe}.png")
        crop.save(path, "PNG")
        count += 1
    print(f"已导出 {count} 张角色区块截图 → {CROPS_DIR}")
    return count


def main():
    blocks = dedup(ocr_full_image())
    blocks = merge_split_values(blocks)
    name_map = build_name_map()
    records = extract(blocks, name_map)
    print(f"提取角色卡: {len(records)}")

    # 写入 character_meta.json
    meta = {}
    if os.path.exists(META_OUT):
        with open(META_OUT, encoding="utf-8") as f:
            meta = json.load(f)
    meta.pop("_schema", None)
    for formal, fields in records.items():
        clean = {k: v for k, v in fields.items() if k != "anchor_box" and v}
        meta[formal] = clean
    with open(META_OUT, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    print(f"已写入 {META_OUT}: {len(meta)} 角色")

    export_crops(records)
    # 记录锚点坐标（供排查）
    anchor = {k: v["anchor_box"] for k, v in records.items()}
    with open(os.path.join(WORK_DIR, "anchors.json"), "w", encoding="utf-8") as f:
        json.dump(anchor, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
