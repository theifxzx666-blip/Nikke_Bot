# -*- coding: utf-8 -*-
"""检查在线详情返回结构。"""
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

print("顶层 keys:", list(d.keys()))
content = d.get("content")
print("content 类型:", type(content).__name__, "长度:", len(str(content)) if content else 0)
s = json.dumps(d, ensure_ascii=False)
print("含技能关键词:", "技能" in s)
print("含 baseData:", "baseData" in s)
print("含 styleData:", "styleData" in s)
# 看 content 开头
if content:
    print("content 前 300:", str(content)[:300])
