# -*- coding: utf-8 -*-
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from law_rag.eval_gold import article_key
from law_rag.llm import chat_stream
from law_rag.online.expand import merge_queries
from law_rag.online.generate import answer_stream
from law_rag.online.intent import classify
from law_rag.online.retrieve import Retriever
from law_rag.online.rewrite import rewrite

CHITCHAT_SYS = (
    "你是面向百姓的法律法规问答助手。用户在闲聊或打招呼。"
    "简短回应即可。若历史里用户刚在咨询具体法律问题，先点出刚才的主题，问要不要继续，不要编造法条。"
    "若没有正在进行的法律问题，说明可以咨询劳动、租房、消费、婚姻家庭、交通等。"
)


class LawQA:
    def __init__(self) -> None:
        self.retriever = Retriever()
        self.sessions: dict[str, list[dict]] = {}

    def _history(self, session_id: str | None, incoming: list[dict] | None) -> list[dict]:
        incoming = incoming or []
        stored = self.sessions.get(session_id or "", [])
        return incoming[-12:] if incoming else stored[-12:]

    def _remember(self, session_id: str | None, history: list[dict], question: str, answer: str) -> None:
        if not session_id:
            return
        turns = list(history)
        turns.append({"role": "user", "content": question})
        turns.append({"role": "assistant", "content": answer})
        self.sessions[session_id] = turns[-12:]

    def retrieve_passages(
        self,
        question: str,
        history: list[dict] | None = None,
        use_rewrite: bool = True,
    ) -> tuple[list[dict[str, Any]], list[str], str]:
        rewritten: list[str] = []
        notes = ""
        if use_rewrite:
            governed = rewrite(question, history)
            rewritten = governed.get("queries") or []
            notes = governed.get("notes") or ""
        queries = merge_queries(question, rewritten)
        best: dict[str, dict[str, Any]] = {}
        for q in queries:
            for hit in self.retriever.search(q):
                cid = str(hit.get("chunk_id") or "")
                if not cid:
                    continue
                prev = best.get(cid)
                if prev is None or float(hit.get("rerank") or 0) > float(prev.get("rerank") or 0):
                    best[cid] = hit
        passages = sorted(best.values(), key=lambda x: float(x.get("rerank") or 0), reverse=True)[:8]
        return passages, queries, notes

    def ask(self, question: str, history: list[dict] | None = None, session_id: str | None = None) -> dict[str, Any]:
        events = list(self.ask_stream(question, history=history, session_id=session_id))
        text = "".join(e.get("text", "") for e in events if e.get("event") == "delta")
        meta = next((e for e in events if e.get("event") == "meta"), {})
        cites = next((e.get("citations") for e in events if e.get("event") == "citations"), [])
        return {
            "intent": meta.get("intent") or "legal",
            "answer": text,
            "citations": cites or [],
            "queries": meta.get("queries") or [],
            "notes": meta.get("notes") or "",
        }

    def ask_stream(
        self,
        question: str,
        history: list[dict] | None = None,
        session_id: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        hist = self._history(session_id, history)
        intent = classify(question, hist)
        buf: list[str] = []

        def pump(chunks: Iterator[str]) -> Iterator[dict[str, Any]]:
            for tok in chunks:
                buf.append(tok)
                yield {"event": "delta", "text": tok}

        if intent == "empty":
            text = "请用一句话描述你遇到的事情，例如：被公司辞退有没有补偿。"
            yield {"event": "meta", "intent": intent, "queries": [], "notes": ""}
            yield {"event": "delta", "text": text}
            yield {"event": "citations", "citations": []}
            yield {"event": "done"}
            self._remember(session_id, hist, question, text)
            return
        if intent == "refuse":
            text = "这个问题我不能提供帮助。如需合法维权，可以说明具体情况，或拨打 12348。"
            yield {"event": "meta", "intent": intent, "queries": [], "notes": ""}
            yield {"event": "delta", "text": text}
            yield {"event": "citations", "citations": []}
            yield {"event": "done"}
            self._remember(session_id, hist, question, text)
            return
        if intent == "chitchat":
            yield {"event": "meta", "intent": intent, "queries": [], "notes": ""}
            messages = [{"role": "system", "content": CHITCHAT_SYS}]
            messages.extend(hist[-8:])
            messages.append({"role": "user", "content": question})
            yield from pump(chat_stream(messages, temperature=0.4, max_tokens=280))
            yield {"event": "citations", "citations": []}
            yield {"event": "done"}
            self._remember(session_id, hist, question, "".join(buf))
            return

        passages, queries, notes = self.retrieve_passages(question, hist)
        yield {"event": "meta", "intent": "legal", "queries": queries, "notes": notes}
        retrieved = [
            {
                "chunk_id": p.get("chunk_id"),
                "law_name": p.get("law_name"),
                "article": p.get("article"),
                "rerank": round(float(p.get("rerank") or 0), 4),
            }
            for p in passages
        ]
        yield {"event": "retrieved", "passages": retrieved}
        yield from pump(answer_stream(question, passages, hist))
        yield {"event": "citations", "citations": _unique_cites(passages)}
        yield {"event": "done"}
        self._remember(session_id, hist, question, "".join(buf))


def _unique_cites(passages: list[dict[str, Any]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    cites: list[dict[str, str]] = []
    for p in passages:
        name = (p.get("law_name") or "").strip()
        art = (p.get("article") or "").strip()
        if not name:
            continue
        key = (name, article_key(art))
        if key in seen:
            continue
        seen.add(key)
        cites.append({"law_name": name, "article": art})
        if len(cites) >= 6:
            break
    return cites
