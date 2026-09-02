# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re

from law_rag.llm import chat

SYS = """你是面向中国百姓的法律咨询问题治理助手。根据用户原话和对话历史，输出 JSON，不要其它文字。
字段：
- queries: 1 到 3 个用于检索全国性法规的规范问句。指代（「那个」「刚才说的」「补偿怎么算」）必须结合历史改写成独立完整问句。
- notes: 简短说明做了拆问/改写/指代消解中的哪一种
硬性要求：
1. 禁止询问省市、地区、户籍。本知识库只有全国性法律、行政法规、司法解释。
2. 一律按全国现行规定改写检索问句。
3. 不要编造用户没说的事实。
4. queries 里必须保留一句接近用户原话的检索句，其余再补规范表述。
"""


def rewrite(question: str, history: list[dict] | None = None) -> dict:
    hist = _fmt_history(history)
    raw = chat(
        [
            {"role": "system", "content": SYS},
            {
                "role": "user",
                "content": f"历史：\n{hist or '无'}\n\n当前问题：{question}",
            },
        ],
        temperature=0.1,
        max_tokens=500,
    )
    data = _parse_json(raw)
    queries = data.get("queries") or [question]
    queries = [str(q).strip() for q in queries if str(q).strip()][:3]
    if question.strip() not in queries:
        queries = [question.strip(), *queries][:3]
    if not queries:
        queries = [question.strip()]
    return {
        "queries": queries,
        "notes": data.get("notes") or "",
    }


def _fmt_history(history: list[dict] | None) -> str:
    if not history:
        return ""
    return "\n".join(f"{m.get('role')}: {m.get('content')}" for m in history[-12:])


def _parse_json(text: str) -> dict:
    text = text.strip()
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return {}
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else {}
    except json.JSONDecodeError:
        return {}
