# -*- coding: utf-8 -*-
from __future__ import annotations

from collections.abc import Iterator

from law_rag.llm import chat_stream


SYS = """你是给中国普通百姓用的法律法规问答助手。必须遵守：
1. 只根据下面「检索条文」回答。不得编造未出现的法名、条号、数字。
2. 检索不足以支撑某一结论时，明确写「这一点检索到的条文不够，不能确定」。
3. 回答结构用这五段，不要用 markdown 标题符号（不要 #）：
   结论要点 → 法律依据（只写检索里出现过的法名+条号）→ 白话解释 → 注意事项 → 可走的下一步。
4. 按全国性法律规定说明；地方可能有细则时，一句话写「请再向当地核实」，不要追问省市。
5. 结合对话历史理解「这个」「那怎么办」等指代。
6. 普法参考，不构成律师意见。语言短、通俗，避免堆砌无关条文。
"""


def _dedup(passages: list[dict]) -> list[dict]:
    best: dict[tuple, dict] = {}
    order: list[tuple] = []
    for p in passages:
        key = (p.get("law_name") or "", p.get("article") or "")
        if not key[0]:
            continue
        cur = best.get(key)
        if cur is None:
            best[key] = p
            order.append(key)
        elif float(p.get("rerank") or 0) > float(cur.get("rerank") or 0):
            best[key] = p
    return [best[k] for k in order]


def answer_stream(
    question: str,
    passages: list[dict],
    history: list[dict] | None = None,
) -> Iterator[str]:
    passages = _dedup(passages)[:6]
    if not passages:
        yield (
            "目前知识库里没有检索到足够对应的现行全国性条文，我不能确定答案。"
            "建议拨打 12348 公共法律服务热线，或向当地法律援助机构咨询。"
        )
        return
    ctx = []
    for i, p in enumerate(passages, 1):
        text = (p.get("text") or "")[:1800]
        ctx.append(f"[{i}] 《{p.get('law_name')}》{p.get('article')}\n{text}")
    hist = ""
    if history:
        hist = "\n".join(
            f"{m.get('role')}: {m.get('content')}" for m in history[-8:]
        )
    messages = [
        {"role": "system", "content": SYS},
        {
            "role": "user",
            "content": (
                f"对话历史：\n{hist or '无'}\n\n"
                f"当前问题：{question}\n\n检索条文：\n" + "\n\n".join(ctx)
            ),
        },
    ]
    yield from chat_stream(messages, temperature=0.15, max_tokens=1400)
