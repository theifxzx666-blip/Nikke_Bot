# -*- coding: utf-8 -*-
"""检查在线详情 data 字段。"""
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

req = urllib.request.Request(
    "https://www.gamekee.com/v1/content/detail/152335", headers=HEADERS
)
with urllib.request.urlopen(req) as r:
    d = json.loads(r.read().decode("utf-8"))

data = d.get("data")
print("data 类型:", type(data).__name__)
if isinstance(data, dict):
    print("data keys:", list(data.keys())[:15])
    s = json.dumps(data, ensure_ascii=False)
    print("含技能:", "技能" in s, "| 含baseData:", "baseData" in s)
    for k, v in data.items():
        if isinstance(v, (dict, list)):
            print(f"  {k}: {type(v).__name__} len={len(v)}")
        else:
            print(f"  {k}: {str(v)[:60]}")
