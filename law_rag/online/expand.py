# -*- coding: utf-8 -*-
from __future__ import annotations

import re

_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"押金|退租"), "房屋租赁期满返还租赁物 押金 民法典"),
    (re.compile(r"七天|无理由退货"), "消费者权益保护法 第二十五条 七日无理由退货"),
    (re.compile(r"辞退|开除|解除劳动合同|经济补偿"), "劳动合同法 违法解除劳动合同 经济补偿 赔偿金"),
    (re.compile(r"加班"), "劳动法 第四十四条 加班费"),
    (re.compile(r"试用期"), "劳动合同法 试用期 第二十一条"),
    (re.compile(r"工伤|上班路上"), "工伤保险条例 第十四条 上下班途中交通事故"),
    (re.compile(r"虚假广告|虚假宣传"), "消费者权益保护法 第二十条 第五十五条 虚假宣传"),
    (re.compile(r"借钱|欠款|不还"), "民法典 借款合同 第六百六十七条 第六百七十五条"),
    (re.compile(r"家暴|家庭暴力"), "民法典 第一千零九十一条 离婚损害赔偿"),
    (re.compile(r"逃逸"), "道路交通安全法 交通事故逃逸"),
    (re.compile(r"离婚.*财产|财产.*离婚"), "民法典 第一千零八十七条 离婚财产分割"),
    (re.compile(r"未成年|小孩.*网"), "民法典 限制民事行为能力 第一百四十五条"),
]


def extra_queries(question: str) -> list[str]:
    q = question or ""
    out: list[str] = []
    for pat, line in _RULES:
        if pat.search(q):
            out.append(line)
        if len(out) >= 2:
            break
    return out


def merge_queries(question: str, rewritten: list[str] | None = None) -> list[str]:
    seen: set[str] = set()
    queries: list[str] = []

    def add(text: str) -> None:
        item = (text or "").strip()
        if not item or item in seen:
            return
        seen.add(item)
        queries.append(item)

    add(question)
    for item in rewritten or []:
        add(item)
    for item in extra_queries(question):
        add(item)
    return queries[:4]
