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
# 区块裁切：按所属列中心动态算列边界（不跨列），裁数据列
# 原图尺寸 2823x12600，每列宽约 650；列中心用首次 OCR 数据动态聚类
KNOWN_COL_CENTERS = [230, 880, 1630, 2280]
CROP_DOWN = 20

# ===== 手工修正（用户对照屑夫蒂原图校对，重跑时自动应用，勿删）=====
MANUAL_FIXES: dict[str, dict] = {
    "灰姑娘": {
        "name": "灰姑娘",
        "strength": "3.5红级别",
        "gear": "4T10，全升级",
        "gear_stat": "4优越、4攻击、1装弹",
        "note": "想12词条可以继续洗双爆",
        "skill": "10/10/10",
        "cube": "战术巨熊",
        "collection": "SR15级",
    },
    "格拉维": {"gear_stat": "优越、攻击、爆伤"},
    "桃乐丝": {"gear_stat": "1+装弹、攻击、优越"},
    "索达：闪亮兔女郎": {"gear_stat": "优越、攻击、1+装弹"},
}


def apply_manual_fixes(meta: dict) -> None:
    """应用手工修正（覆盖 OCR 提取值，重跑可复现）。"""
    for name, fixes in MANUAL_FIXES.items():
        if name not in meta:
            meta[name] = {}
        meta[name].update(fixes)
        print(f"  ✏️ 手工修正 {name}: {json.dumps(fixes, ensure_ascii=False)}")

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
        fields = {"name": formal, "note": "", "anchor_box": b["box"], "data_top": None, "data_right": None}
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
            if matched:
                if fields["data_top"] is None or oy < fields["data_top"]:
                    fields["data_top"] = oy
            # 该列字段区所有文本块的右边缘（含 label + 续行）
            if oy >= (fields["data_top"] or (cy - 450)):
                ox1 = ob["box"][2]
                if fields["data_right"] is None or ox1 > fields["data_right"]:
                    fields["data_right"] = ox1
        records[formal] = fields
    return records


def export_crops(records):
    """裁剪每个角色的原图区块：水平=完整一列（含立绘），垂直=本行边界（不混入上一行）"""
    os.makedirs(CROPS_DIR, exist_ok=True)
    img = Image.open(SRC).convert("RGB")
    W, H = img.size
    cols = sorted(KNOWN_COL_CENTERS)
    # 所有锚点按 y 排序（用于找上一行的下边界）
    anchors = sorted(records.values(), key=lambda f: f["anchor_box"][1])
    count = 0
    for i, fields in enumerate(anchors):
        x0, y0, x1, y1 = fields["anchor_box"]
        cy = (y0 + y1) / 2
        cx = (x0 + x1) / 2
        idx = min(range(len(cols)), key=lambda j: abs(cols[j] - cx))
        col_c = cols[idx]
        # 列边界（完整列：立绘 + 数据）
        col_left = (cols[idx - 1] + col_c) // 2 if idx > 0 else 0
        col_right = (col_c + cols[idx + 1]) // 2 if idx < len(cols) - 1 else W
        left = max(0, col_left)
        # 右边：取字段实际最大 x（避免文字截断），但不超下一列文字起头 - 100 间隙
        next_col_c = cols[idx + 1] if idx < len(cols) - 1 else None
        max_x = fields.get("data_right") or col_right
        if next_col_c:
            # 下一列字段大概从 next_col_c - 150 开始
            right = min(W, max(col_right, max_x + 10), next_col_c - 150)
        else:
            right = min(W, max(col_right, max_x + 10))
        # 垂直上边界：直接用字段区顶部（data_top），保证本行完整、上一行不混入
        # （如灰姑娘 data_top=5975 是"3.5红级"强度评级，向上不会再有上一行内容）
        dt = fields.get("data_top")
        top = max(0, int(dt - 20)) if dt else max(0, int(cy - 300))
        bottom = min(H, int(y1 + CROP_DOWN))
        crop = img.crop((left, top, right, bottom))
        # 放大 1.5x 便于查看
        w, h = crop.size
        crop = crop.resize((int(w * 1.5), int(h * 1.5)), Image.LANCZOS)
        # 文件名：去冒号等非法字符
        import re as _re
        safe = _re.sub(r'[\\/:*?"<>|]', "", fields["name"])
        path = os.path.join(CROPS_DIR, f"{safe}.png")
        crop.save(path, "PNG")
        count += 1
    print(f"已导出 {count} 张角色区块截图（完整列+行边界） → {CROPS_DIR}")
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
        clean = {k: v for k, v in fields.items() if k not in ("anchor_box", "data_top", "data_right") and v}
        meta[formal] = clean
    # 应用手工修正（用户对照原图校对，覆盖 OCR 值）
    apply_manual_fixes(meta)
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
