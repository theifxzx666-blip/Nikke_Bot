# -*- coding: utf-8 -*-
"""GameKee 在线兜底查询（P2）。

本地 WikiIndex 未命中时，按名称走 GameKee 在线检索：
  1. 目录树接口按角色名精确匹配 -> content_id
  2. 详情接口 -> content_cdn 地址
  3. CDN 拉取技能内容 JSON

只读在线数据，不写入本地缓存（保持与 Nikke_Wiki 数据目录解耦）。
"""

from __future__ import annotations

import json
import logging
import socket
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

GAMEKEE_TREE_URL = "https://www.gamekee.com/v1/entry/treesByPid?pid=64581"
GAMEKEE_DETAIL_URL = "https://www.gamekee.com/v1/content/detail/{content_id}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json,text/plain,*/*",
    "X-Requested-With": "XMLHttpRequest",
    "game-alias": "nikke",
    "Lang": "zh-cn",
    "device-num": "1",
    "Referer": "https://www.gamekee.com/nikke/second/64581",
}

DEFAULT_TIMEOUT = 20
TREE_CACHE_TTL = 3600  # 目录树缓存 1 小时（避免每次查询都拉 199 角色）


def _request_json(url: str, timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any] | None:
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
        return json.loads(raw.decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, socket.timeout, json.JSONDecodeError) as exc:
        logger.warning("GameKee 请求失败 %s: %s", url, exc)
        return None


# 目录树进程内缓存（TTL 1 小时）
_tree_cache: dict[str, Any] = {"ts": 0.0, "data": None}


def _fetch_role_tree() -> list[dict[str, Any]] | None:
    """拉取/缓存角色目录树，返回角色节点列表。"""
    import time

    now = time.time()
    if _tree_cache["data"] is not None and now - _tree_cache["ts"] < TREE_CACHE_TTL:
        return _tree_cache["data"]
    data = _request_json(GAMEKEE_TREE_URL)
    if not data or data.get("code") != 0:
        return None
    try:
        roles = data["data"][0]["child"]
    except (KeyError, IndexError, TypeError):
        return None
    _tree_cache.update(ts=now, data=roles)
    return roles


def search_role(name: str) -> dict[str, Any] | None:
    """按名称在线搜索角色，返回角色节点（含 content_id）。

    依次尝试：原名精确 -> 去标点精确 -> 包含匹配。
    """
    roles = _fetch_role_tree()
    if not roles:
        return None
    query = str(name).strip()
    if not query:
        return None

    def norm(text: str) -> str:
        return "".join(ch for ch in text if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")

    query_norm = norm(query)

    # 1. 原名精确
    for role in roles:
        if str(role.get("name") or "").strip() == query:
            return role
    # 2. 别名精确
    for role in roles:
        alias = str(role.get("name_alias") or "").strip()
        if alias and alias == query:
            return role
    # 3. 去标点精确（处理 normalize 已去冒号的情况）
    for role in roles:
        if norm(str(role.get("name") or "")) == query_norm:
            return role
    # 4. 包含匹配（宽松，用于在线兜底）
    for role in roles:
        if query_norm and query_norm in norm(str(role.get("name") or "")):
            return role
    return None


def fetch_content_cdn(content_id: int) -> str | None:
    """详情接口拿 content_cdn 地址（补全协议并替换为可访问 CDN）。"""
    data = _request_json(GAMEKEE_DETAIL_URL.format(content_id=content_id))
    if not data or data.get("code") != 0:
        return None
    try:
        cdn = data["data"]["content_cdn"]
    except (KeyError, TypeError):
        return None
    if not cdn:
        return None
    if cdn.startswith("//"):
        cdn = "https:" + cdn
    return cdn.replace("https://api-cdn.gamekee.com/", "https://cdnimg-v2.gamekee.com/")


def fetch_online_payload(content_id: int) -> dict[str, Any] | None:
    """完整拉取在线技能内容（baseData 行列表）。"""
    cdn = fetch_content_cdn(content_id)
    if not cdn:
        return None
    payload = _request_json(cdn)
    if not payload:
        return None
    try:
        inner = json.loads(payload.get("content") or "{}")
        base = inner.get("baseData") or []
        return {"baseData": base}
    except (json.JSONDecodeError, AttributeError):
        return None
