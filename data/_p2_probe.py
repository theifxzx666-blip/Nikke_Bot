# -*- coding: utf-8 -*-
"""P2 在线接口探测：目录树 + 详情。"""
import json
import socket
import urllib.request

socket.setdefaulttimeout(20)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json,text/plain,*/*",
    "X-Requested-With": "XMLHttpRequest",
    "game-alias": "nikke",
    "Lang": "zh-cn",
    "device-num": "1",
    "Referer": "https://www.gamekee.com/nikke/second/64581",
}


def get(url: str) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req) as r:
        return r.status, r.read()


# 1. 目录树
s, raw = get("https://www.gamekee.com/v1/entry/treesByPid?pid=64581")
d = json.loads(raw.decode("utf-8"))
print("树: HTTP", s, "code", d.get("code"))
roles = d["data"][0]["child"]
print("角色数:", len(roles))
honglian = [r for r in roles if r.get("name") == "红莲"]
if honglian:
    node = honglian[0]
    print("红莲节点:", json.dumps(node, ensure_ascii=False)[:400])
    cid = node.get("content_id") or node.get("contentId")
    print("content_id:", cid)
    # 2. 详情
    try:
        s2, raw2 = get(f"https://www.gamekee.com/v1/content/detail/{cid}")
        d2 = json.loads(raw2.decode("utf-8"))
        print("详情: HTTP", s2, "code", d2.get("code"))
        inner = json.loads(d2.get("content", "{}"))
        print("详情含技能:", "技能1名称" in json.dumps(inner, ensure_ascii=False))
        print("详情含珍藏品:", "珍藏品名称" in json.dumps(inner, ensure_ascii=False))
    except Exception as e:
        print("详情失败:", type(e).__name__, e)
else:
    print("未找到红莲")
