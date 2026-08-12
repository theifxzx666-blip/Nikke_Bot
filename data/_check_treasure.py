# -*- coding: utf-8 -*-
"""精确检查：缓存含真实珍藏品名称但词典未确认的角色。"""
import json
import os

from guild_war_bot.wiki_query import default_index

idx = default_index()
cache_dir = r"F:/Codex/Nikke/Nikke_Wiki/cache/gamekee_content_details"

confirmed = set()
for rec in idx.characters:
    fav = rec.get("favoriteItem")
    if isinstance(fav, dict) and fav.get("status") == "已确认":
        confirmed.add(rec.get("cnName") or rec.get("name"))

real_treasure = []
for rec in idx.characters:
    name = rec.get("cnName") or rec.get("name")
    cid = rec.get("gamekeeContentId")
    if not cid:
        continue
    path = os.path.join(cache_dir, f"content_{cid}.json")
    if not os.path.exists(path):
        continue
    try:
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
        inner = json.loads(data.get("content") or "{}")
        base = inner.get("baseData") or []
        for row in base:
            if not isinstance(row, list):
                continue
            cells = [c.get("value", "") for c in row if isinstance(c, dict)]
            if (
                cells
                and cells[0] == "珍藏品名称"
                and len(cells) > 1
                and cells[1].strip()
            ):
                real_treasure.append((name, cells[1], cid, name in confirmed))
                break
    except Exception:
        pass

print(f"缓存中确认有珍藏品名称的角色: {len(real_treasure)} 个")
unmarked = [(n, item, cid) for n, item, cid, marked in real_treasure if not marked]
print(f"其中词典未标「已确认」的: {len(unmarked)} 个")
for n, item, cid in unmarked:
    print(f"  ⚠️ {n}: {item} (contentId={cid})")
