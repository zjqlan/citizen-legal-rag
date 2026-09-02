# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
from typing import Any

from law_rag import settings as S

CN = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def cn_to_int(s: str) -> int | None:
    s = (s or "").strip().replace("零", "").replace("〇", "")
    if not s:
        return None
    if s.isdigit():
        return int(s)
    if s == "十":
        return 10
    n = 0
    if "千" in s:
        left, _, rest = s.partition("千")
        n += (CN.get(left, 1) if left else 1) * 1000
        s = rest
    if "百" in s:
        left, _, rest = s.partition("百")
        n += (CN.get(left, 1) if left else 1) * 100
        s = rest
    if "十" in s:
        left, _, rest = s.partition("十")
        tens = 1 if not left else CN.get(left, 1)
        n += tens * 10
        s = rest
    if s:
        n += CN.get(s, 0)
    return n or None


def article_key(text: str) -> str:
    raw = (text or "").replace(" ", "")
    m = re.search(r"第([零〇一二三四五六七八九十百千两0-9]+)条", raw)
    if not m:
        return raw
    n = cn_to_int(m.group(1))
    return f"第{n}条" if n else raw


def law_match(a: str, b: str) -> bool:
    a = (a or "").replace("《", "").replace("》", "").strip()
    b = (b or "").replace("《", "").replace("》", "").strip()
    if not a or not b:
        return False
    return a == b or a in b or b in a


def load_gold() -> list[dict[str, Any]]:
    if not S.GOLD_PATH.exists():
        return []
    items = []
    for line in S.GOLD_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            items.append(json.loads(line))
    return items


def hit_rank(gold: list[dict], retrieved: list[dict]) -> int | None:
    for i, hit in enumerate(retrieved, 1):
        for g in gold:
            if law_match(g.get("law_name", ""), hit.get("law_name", "")) and article_key(
                g.get("article", "")
            ) == article_key(hit.get("article", "")):
                return i
    return None
