# -*- coding: utf-8 -*-
"""按「条」切分法规；超长条按「款」做父子块；无条结构用滑动窗口。"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from law_rag import settings as S

ARTICLE_RE = re.compile(
    r"(?:(?<=\n)|(?<=^))[ \u3000]*("
    r"第[零〇一二三四五六七八九十百千万两0-9]+条"
    r"(?:之[零〇一二三四五六七八九十百千0-9]+)?)"
    r"[ \u3000]*"
)
HEADING_RE = re.compile(
    r"^[ \u3000]*(第[零〇一二三四五六七八九十百千0-9]+(?:编|章|节)\S{0,40})$",
    re.M,
)
KUAI_RE = re.compile(
    r"(?:(?<=\n)|(?<=^))[ \u3000]*([（(][一二三四五六七八九十百0-9]+[）)])"
)
HEADER_RE = re.compile(
    r"^标题：(?P<title>.+)\n"
    r"制定机关：(?P<office>.*)\n"
    r"公布日期：(?P<publish>.*)\n"
    r"施行日期：(?P<effective>.*)\n"
    r"效力：(?P<status>.*)\n"
    r"类型：(?P<doc_type>.*)\n"
    r"来源：(?P<source>.*)\n"
    r"=+\n*",
    re.M,
)


def _sid(*parts: str) -> str:
    raw = "||".join(parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _strip_header(raw: str) -> tuple[dict[str, str], str]:
    m = HEADER_RE.match(raw)
    if not m:
        return {}, raw.strip()
    meta = {k: (v or "").strip() for k, v in m.groupdict().items()}
    return meta, raw[m.end() :].strip()


def _current_headings(text_before: str) -> dict[str, str]:
    book = chapter = section = ""
    for m in HEADING_RE.finditer(text_before):
        line = m.group(1).strip()
        if "编" in line[:8]:
            book = line
        elif "章" in line[:8]:
            chapter = line
        elif "节" in line[:8]:
            section = line
    return {"book": book, "chapter": chapter, "section": section}


def _prefix(law: str, status: str, heads: dict[str, str], article: str) -> str:
    bits = [f"《{law}》", status]
    for key in ("book", "chapter", "section"):
        if heads.get(key):
            bits.append(heads[key])
    bits.append(article)
    return "｜".join(bits)


def _split_kuai(article_text: str) -> list[tuple[int, str]]:
    starts = [m.start() for m in KUAI_RE.finditer(article_text)]
    if len(starts) < 2:
        return []
    if starts[0] > 40:
        starts = [0] + starts
    parts: list[tuple[int, str]] = []
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else len(article_text)
        chunk = article_text[s:e].strip()
        if chunk:
            parts.append((i, chunk))
    return parts if len(parts) >= 2 else []


def _windows(text: str, size: int, overlap: int) -> list[str]:
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    out = []
    i = 0
    while i < len(text):
        out.append(text[i : i + size].strip())
        if i + size >= len(text):
            break
        i += max(1, size - overlap)
    return [x for x in out if x]


def chunk_body(law_name: str, status: str, body: str, doc_id: str) -> list[dict[str, Any]]:
    matches = list(ARTICLE_RE.finditer(body))
    chunks: list[dict[str, Any]] = []
    if not matches:
        for i, win in enumerate(_windows(body, S.WINDOW_SIZE, S.WINDOW_OVERLAP)):
            heads = _current_headings(body[:200])
            prefix = _prefix(law_name, status, heads, f"片段{i + 1}")
            text = f"{prefix}\n{win}"
            chunks.append(
                {
                    "chunk_id": _sid(doc_id, "window", str(i), win[:80]),
                    "article": f"片段{i + 1}",
                    "paragraph": 0,
                    "chunk_type": "window",
                    "parent_id": "",
                    "book": heads.get("book", ""),
                    "chapter": heads.get("chapter", ""),
                    "section": heads.get("section", ""),
                    "text": text,
                }
            )
        return chunks

    preamble = body[: matches[0].start()].strip()
    if preamble and len(re.sub(r"\s+", "", preamble)) > 8:
        heads = _current_headings(preamble)
        prefix = _prefix(law_name, status, heads, "题注")
        chunks.append(
            {
                "chunk_id": _sid(doc_id, "题注", preamble[:80]),
                "article": "题注",
                "paragraph": 0,
                "chunk_type": "article",
                "parent_id": "",
                "book": heads.get("book", ""),
                "chapter": heads.get("chapter", ""),
                "section": heads.get("section", ""),
                "text": f"{prefix}\n{preamble}",
            }
        )

    for i, m in enumerate(matches):
        art = m.group(1)
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        piece = body[start:end].strip()
        heads = _current_headings(body[:start])
        prefix = _prefix(law_name, status, heads, art)
        parent_text = f"{prefix}\n{piece}"
        parent_id = _sid(doc_id, art, "parent")
        kuai = _split_kuai(piece) if len(piece) >= S.LONG_ARTICLE_CHARS else []
        if kuai:
            chunks.append(
                {
                    "chunk_id": parent_id,
                    "article": art,
                    "paragraph": 0,
                    "chunk_type": "parent",
                    "parent_id": "",
                    "book": heads.get("book", ""),
                    "chapter": heads.get("chapter", ""),
                    "section": heads.get("section", ""),
                    "text": parent_text,
                }
            )
            for pi, ptxt in kuai:
                child_id = _sid(doc_id, art, f"p{pi}", ptxt[:60])
                cprefix = _prefix(law_name, status, heads, f"{art}款{pi + 1}")
                chunks.append(
                    {
                        "chunk_id": child_id,
                        "article": art,
                        "paragraph": pi + 1,
                        "chunk_type": "child",
                        "parent_id": parent_id,
                        "book": heads.get("book", ""),
                        "chapter": heads.get("chapter", ""),
                        "section": heads.get("section", ""),
                        "text": f"{cprefix}\n{ptxt}",
                    }
                )
        else:
            chunks.append(
                {
                    "chunk_id": _sid(doc_id, art, piece[:80]),
                    "article": art,
                    "paragraph": 0,
                    "chunk_type": "article",
                    "parent_id": "",
                    "book": heads.get("book", ""),
                    "chapter": heads.get("chapter", ""),
                    "section": heads.get("section", ""),
                    "text": parent_text,
                }
            )
    return chunks


def process_all() -> dict[str, Any]:
    S.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, dict] = {}
    if S.RAW_MANIFEST.exists():
        for line in S.RAW_MANIFEST.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            title = rec.get("title") or ""
            manifest[title] = rec

    files = sorted(S.RAW_TEXT_DIR.glob("*.txt"))
    doc_types: Counter[str] = Counter()
    chunk_types: Counter[str] = Counter()
    n_docs = n_chunks = empty = 0

    with S.DOCUMENTS_PATH.open("w", encoding="utf-8") as df, S.CHUNKS_PATH.open(
        "w", encoding="utf-8"
    ) as cf:
        for path in files:
            raw = path.read_text(encoding="utf-8")
            header, body = _strip_header(raw)
            if not body.strip():
                empty += 1
                continue
            title = header.get("title") or path.stem.rsplit("_", 1)[0]
            man = manifest.get(title, {})
            doc_id = man.get("bbbs") or _sid(path.name)
            status = header.get("status") or man.get("status") or "有效"
            doc_type = header.get("doc_type") or man.get("type") or "法律"
            doc = {
                "doc_id": doc_id,
                "title": title,
                "office": header.get("office") or man.get("office") or "",
                "publish": header.get("publish") or man.get("publish") or "",
                "effective": header.get("effective") or man.get("effective") or "",
                "status": status,
                "doc_type": doc_type,
                "region": "全国",
                "source": header.get("source") or man.get("source") or "",
                "chars": len(body),
                "path": str(path.relative_to(S.ROOT)).replace("\\", "/"),
            }
            parts = chunk_body(title, status, body, doc_id)
            if not parts:
                empty += 1
                continue
            doc["n_chunks"] = len(parts)
            df.write(json.dumps(doc, ensure_ascii=False) + "\n")
            for ch in parts:
                rec = {
                    **ch,
                    "doc_id": doc_id,
                    "law_name": title,
                    "doc_type": doc_type,
                    "status": status,
                    "region": "全国",
                    "office": doc["office"],
                    "publish": doc["publish"],
                    "effective": doc["effective"],
                }
                cf.write(json.dumps(rec, ensure_ascii=False) + "\n")
                chunk_types[ch["chunk_type"]] += 1
            doc_types[doc_type] += 1
            n_docs += 1
            n_chunks += len(parts)

    stats = {
        "documents": n_docs,
        "chunks": n_chunks,
        "empty_skipped": empty,
        "doc_types": dict(doc_types),
        "chunk_types": dict(chunk_types),
        "documents_path": S._rel(S.DOCUMENTS_PATH),
        "chunks_path": S._rel(S.CHUNKS_PATH),
        "strategy": "按条切分；超长条按款做父子块；无条结构用滑动窗口",
    }
    S.STATS_PATH.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    return stats
