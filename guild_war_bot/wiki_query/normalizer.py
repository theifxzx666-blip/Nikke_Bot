# -*- coding: utf-8 -*-
"""查询词归一化（黑话/昵称对齐）。

- 去除 @机器人、斜杠前缀、空白与常见标点
- 全角转半角（／→/、！→! 等）
- 英文名大小写折叠
"""

from __future__ import annotations

import re

_STRIP_RE = re.compile(r"^@\S+\s*")
_SLASH_RE = re.compile(r"^[/／]+")
_SPACE_RE = re.compile(r"[\s\u3000]+")
_PUNCT_RE = re.compile(r"[，。！？、；：,.!?;:()（）【】\[\]\"'\"']")

_FULL_TO_HALF = str.maketrans(
    "！＂＃＄％＆＇（）＊＋，－．／：；＜＝＞？＠［＼］＾＿｀｛｜｝～",
    "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~",
)


def normalize_query(text: str) -> str:
    """把群消息里的查询串归一化为可索引的形式（如「/角色 红莲」→「红莲」）。"""
    content = text.strip()
    content = _STRIP_RE.sub("", content)
    content = _SLASH_RE.sub("", content)
    content = content.translate(_FULL_TO_HALF)
    content = _PUNCT_RE.sub("", content)
    content = _SPACE_RE.sub(" ", content)
    return content.strip()


def extract_after_keyword(text: str, keywords: tuple[str, ...]) -> str | None:
    """若文本以某关键词开头，返回其后的参数部分（已归一化）；否则返回 None。

    例：extract_after_keyword("/角色 红莲", ("角色", "查角色")) -> "红莲"
    """
    content = normalize_query(text)
    lowered = content.lower()
    for kw in keywords:
        k = kw.lower()
        if lowered == k:
            return ""
        if lowered.startswith(k) and (len(lowered) > len(k)):
            return content[len(k) :].strip()
    return None
