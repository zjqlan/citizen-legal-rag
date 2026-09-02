# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from law_rag import settings as S

_lock = threading.Lock()
_chunks_ready = False
_chunks_error: str | None = None


def conn() -> sqlite3.Connection:
    S.USER_DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(S.USER_DB, check_same_thread=False, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def _rows(items: list[sqlite3.Row] | sqlite3.Row | None) -> Any:
    if items is None:
        return None
    if isinstance(items, sqlite3.Row):
        return dict(items)
    return [dict(r) for r in items]


def init_db() -> None:
    with conn() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at REAL NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        cols = {r[1] for r in con.execute("PRAGMA table_info(users)")}
        if "is_admin" not in cols:
            con.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '新对话',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                username TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                intent TEXT DEFAULT '',
                citations TEXT DEFAULT '[]',
                retrieved TEXT DEFAULT '[]',
                queries TEXT DEFAULT '[]',
                latency_ms REAL DEFAULT 0,
                created_at REAL NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER NOT NULL,
                conversation_id TEXT NOT NULL,
                username TEXT NOT NULL,
                rating INTEGER NOT NULL,
                comment TEXT DEFAULT '',
                created_at REAL NOT NULL,
                UNIQUE(message_id, username)
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS eval_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at REAL NOT NULL,
                finished_at REAL NOT NULL,
                n INTEGER NOT NULL,
                recall_at_k REAL NOT NULL,
                mrr REAL NOT NULL,
                citation_hit REAL NOT NULL,
                detail TEXT NOT NULL
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id TEXT PRIMARY KEY,
                law_name TEXT,
                article TEXT,
                doc_type TEXT,
                chunk_type TEXT,
                status TEXT,
                chapter TEXT,
                text TEXT
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS kv (
                k TEXT PRIMARY KEY,
                v TEXT
            )
            """
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations(username, updated_at DESC)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id, id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_fb_msg ON feedback(message_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_chunks_law ON chunks(law_name)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_chunks_type ON chunks(chunk_type, doc_type)")
    _ensure_admin()


def _ensure_admin() -> None:
    from law_rag.auth import _hash_password

    name = (S.ADMIN_USERNAME or "admin").strip()
    password = (S.ADMIN_PASSWORD or "").strip()
    if not password:
        return
    now = time.time()
    with conn() as con:
        row = con.execute("SELECT username FROM users WHERE username = ?", (name,)).fetchone()
        if row:
            con.execute("UPDATE users SET is_admin = 1 WHERE username = ?", (name,))
        else:
            con.execute(
                "INSERT INTO users (username, password_hash, created_at, is_admin) VALUES (?, ?, ?, 1)",
                (name, _hash_password(password), now),
            )


def is_admin(username: str) -> bool:
    with conn() as con:
        row = con.execute("SELECT is_admin FROM users WHERE username = ?", (username,)).fetchone()
    return bool(row and row["is_admin"])


def chunks_status() -> dict[str, Any]:
    return {"ok": _chunks_ready, "error": _chunks_error}


def ensure_chunk_index() -> None:
    global _chunks_ready, _chunks_error
    path = S.CHUNKS_PATH
    if not path.exists():
        _chunks_error = "尚未生成分块文件"
        _chunks_ready = False
        return
    sig = f"{path.stat().st_mtime_ns}:{path.stat().st_size}"
    with conn() as con:
        saved = con.execute("SELECT v FROM kv WHERE k = 'chunk_sig'").fetchone()
        n = con.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"]
        if saved and saved["v"] == sig and n > 0:
            _chunks_ready = True
            _chunks_error = None
            return
    try:
        _rebuild_chunks(path, sig)
        _chunks_ready = True
        _chunks_error = None
    except Exception as exc:
        _chunks_error = str(exc)
        _chunks_ready = False


def _rebuild_chunks(path: Path, sig: str) -> None:
    batch: list[tuple] = []
    with path.open(encoding="utf-8") as f, conn() as con:
        con.execute("DELETE FROM chunks")
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            batch.append(
                (
                    rec.get("chunk_id") or "",
                    rec.get("law_name") or "",
                    rec.get("article") or "",
                    rec.get("doc_type") or "",
                    rec.get("chunk_type") or "",
                    rec.get("status") or "",
                    rec.get("chapter") or "",
                    (rec.get("text") or "")[:8000],
                )
            )
            if len(batch) >= 800:
                con.executemany(
                    "INSERT OR REPLACE INTO chunks VALUES (?,?,?,?,?,?,?,?)",
                    batch,
                )
                batch.clear()
        if batch:
            con.executemany(
                "INSERT OR REPLACE INTO chunks VALUES (?,?,?,?,?,?,?,?)",
                batch,
            )
        con.execute("INSERT OR REPLACE INTO kv(k, v) VALUES ('chunk_sig', ?)", (sig,))


def chunk_stats() -> dict[str, Any]:
    stats = {}
    if S.STATS_PATH.exists():
        stats = json.loads(S.STATS_PATH.read_text(encoding="utf-8"))
    with conn() as con:
        indexed = con.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"]
        types = {
            r["chunk_type"]: r["n"]
            for r in con.execute(
                "SELECT chunk_type, COUNT(*) AS n FROM chunks GROUP BY chunk_type"
            )
        }
        docs = {
            r["doc_type"]: r["n"]
            for r in con.execute(
                "SELECT doc_type, COUNT(*) AS n FROM chunks GROUP BY doc_type"
            )
        }
        laws = con.execute("SELECT COUNT(DISTINCT law_name) AS n FROM chunks").fetchone()["n"]
    return {
        "processed": stats,
        "indexed": indexed,
        "chunk_types": types,
        "doc_types": docs,
        "laws": laws,
        "strategy": stats.get("strategy") or "按条切分；超长条按款做父子块；无条结构用滑动窗口",
        "ready": _chunks_ready,
        "error": _chunks_error,
    }


def search_chunks(
    q: str = "",
    doc_type: str = "",
    chunk_type: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    page = max(1, page)
    page_size = min(50, max(1, page_size))
    where = ["1=1"]
    args: list[Any] = []
    if q.strip():
        where.append("(law_name LIKE ? OR article LIKE ? OR text LIKE ?)")
        like = f"%{q.strip()}%"
        args.extend([like, like, like])
    if doc_type:
        where.append("doc_type = ?")
        args.append(doc_type)
    if chunk_type:
        where.append("chunk_type = ?")
        args.append(chunk_type)
    sql = " FROM chunks WHERE " + " AND ".join(where)
    with conn() as con:
        total = con.execute("SELECT COUNT(*) AS n" + sql, args).fetchone()["n"]
        rows = con.execute(
            "SELECT chunk_id, law_name, article, doc_type, chunk_type, status, chapter, "
            "substr(text, 1, 220) AS preview" + sql + " ORDER BY law_name, article LIMIT ? OFFSET ?",
            [*args, page_size, (page - 1) * page_size],
        ).fetchall()
    return {"total": total, "page": page, "page_size": page_size, "items": _rows(rows)}


def get_chunk(chunk_id: str) -> dict[str, Any] | None:
    with conn() as con:
        row = con.execute("SELECT * FROM chunks WHERE chunk_id = ?", (chunk_id,)).fetchone()
    return _rows(row)


def list_conversations(username: str) -> list[dict[str, Any]]:
    with conn() as con:
        rows = con.execute(
            """
            SELECT c.id, c.title, c.updated_at, c.created_at,
                   (SELECT substr(content, 1, 80) FROM messages
                    WHERE conversation_id = c.id AND role = 'user'
                    ORDER BY id DESC LIMIT 1) AS preview
            FROM conversations c
            WHERE c.username = ?
            ORDER BY c.updated_at DESC
            LIMIT 80
            """,
            (username,),
        ).fetchall()
    return _rows(rows)


def get_conversation(username: str, conv_id: str) -> dict[str, Any] | None:
    with conn() as con:
        conv = con.execute(
            "SELECT * FROM conversations WHERE id = ? AND username = ?",
            (conv_id, username),
        ).fetchone()
        if not conv:
            return None
        msgs = con.execute(
            """
            SELECT m.id, m.role, m.content, m.intent, m.citations, m.created_at,
                   f.rating AS feedback
            FROM messages m
            LEFT JOIN feedback f ON f.message_id = m.id AND f.username = m.username
            WHERE m.conversation_id = ?
            ORDER BY m.id
            """,
            (conv_id,),
        ).fetchall()
    out = dict(conv)
    items = []
    for m in msgs:
        rec = dict(m)
        try:
            rec["citations"] = json.loads(rec.get("citations") or "[]")
        except json.JSONDecodeError:
            rec["citations"] = []
        items.append(rec)
    out["messages"] = items
    return out


def create_conversation(username: str, title: str = "新对话") -> str:
    cid = uuid.uuid4().hex
    now = time.time()
    with conn() as con:
        con.execute(
            "INSERT INTO conversations (id, username, title, created_at, updated_at) VALUES (?,?,?,?,?)",
            (cid, username, title[:40] or "新对话", now, now),
        )
    return cid


def own_conversation(username: str, conv_id: str | None) -> str:
    if not conv_id:
        return create_conversation(username)
    with conn() as con:
        row = con.execute(
            "SELECT id FROM conversations WHERE id = ? AND username = ?",
            (conv_id, username),
        ).fetchone()
    return row["id"] if row else create_conversation(username)


def save_turn(
    username: str,
    conversation_id: str | None,
    question: str,
    answer: str,
    intent: str,
    citations: list[dict],
    retrieved: list[dict],
    queries: list[str],
    latency_ms: float,
) -> dict[str, Any]:
    cid = own_conversation(username, conversation_id)
    now = time.time()
    title = question.strip().replace("\n", " ")[:28] or "新对话"
    with conn() as con:
        n = con.execute(
            "SELECT COUNT(*) AS n FROM messages WHERE conversation_id = ?", (cid,)
        ).fetchone()["n"]
        if n == 0:
            con.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                (title, now, cid),
            )
        else:
            con.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, cid))
        cur = con.execute(
            """
            INSERT INTO messages (conversation_id, username, role, content, intent, citations,
                                  retrieved, queries, latency_ms, created_at)
            VALUES (?, ?, 'user', ?, ?, '[]', '[]', '[]', 0, ?)
            """,
            (cid, username, question, intent, now),
        )
        user_mid = cur.lastrowid
        cur = con.execute(
            """
            INSERT INTO messages (conversation_id, username, role, content, intent, citations,
                                  retrieved, queries, latency_ms, created_at)
            VALUES (?, ?, 'assistant', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cid,
                username,
                answer,
                intent,
                json.dumps(citations, ensure_ascii=False),
                json.dumps(retrieved, ensure_ascii=False),
                json.dumps(queries, ensure_ascii=False),
                latency_ms,
                now,
            ),
        )
        bot_mid = cur.lastrowid
    return {"conversation_id": cid, "user_message_id": user_mid, "message_id": bot_mid}


def save_feedback(username: str, message_id: int, rating: int, comment: str = "") -> None:
    if rating not in (1, -1):
        raise ValueError("评分只能是有用或无用")
    with conn() as con:
        row = con.execute(
            "SELECT id, conversation_id, role FROM messages WHERE id = ? AND username = ?",
            (message_id, username),
        ).fetchone()
        if not row or row["role"] != "assistant":
            raise ValueError("找不到这条回答")
        con.execute(
            """
            INSERT INTO feedback (message_id, conversation_id, username, rating, comment, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(message_id, username) DO UPDATE SET
                rating = excluded.rating,
                comment = excluded.comment,
                created_at = excluded.created_at
            """,
            (message_id, row["conversation_id"], username, rating, (comment or "")[:500], time.time()),
        )


def overview() -> dict[str, Any]:
    with conn() as con:
        users = con.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
        convs = con.execute("SELECT COUNT(*) AS n FROM conversations").fetchone()["n"]
        msgs = con.execute("SELECT COUNT(*) AS n FROM messages").fetchone()["n"]
        asks = con.execute(
            "SELECT COUNT(*) AS n FROM messages WHERE role = 'user'"
        ).fetchone()["n"]
        legal = con.execute(
            "SELECT COUNT(*) AS n FROM messages WHERE role = 'assistant' AND intent = 'legal'"
        ).fetchone()["n"]
        good = con.execute(
            "SELECT COUNT(*) AS n FROM feedback WHERE rating = 1"
        ).fetchone()["n"]
        bad = con.execute(
            "SELECT COUNT(*) AS n FROM feedback WHERE rating = -1"
        ).fetchone()["n"]
        intents = {
            r["intent"] or "unknown": r["n"]
            for r in con.execute(
                "SELECT intent, COUNT(*) AS n FROM messages WHERE role = 'assistant' GROUP BY intent"
            )
        }
        recent = _rows(
            con.execute(
                """
                SELECT m.id, m.username, m.content, m.intent, m.created_at, c.title
                FROM messages m
                JOIN conversations c ON c.id = m.conversation_id
                WHERE m.role = 'user'
                ORDER BY m.id DESC LIMIT 12
                """
            ).fetchall()
        )
        top_users = _rows(
            con.execute(
                """
                SELECT username, COUNT(*) AS n, MAX(created_at) AS last_at
                FROM messages WHERE role = 'user'
                GROUP BY username ORDER BY n DESC LIMIT 8
                """
            ).fetchall()
        )
    kb = json.loads(S.STATS_PATH.read_text(encoding="utf-8")) if S.STATS_PATH.exists() else {}
    return {
        "users": users,
        "conversations": convs,
        "messages": msgs,
        "questions": asks,
        "legal_answers": legal,
        "feedback_good": good,
        "feedback_bad": bad,
        "intents": intents,
        "recent_questions": recent,
        "top_users": top_users,
        "kb": {
            "documents": kb.get("documents"),
            "chunks": kb.get("chunks"),
            "doc_types": kb.get("doc_types"),
            "chunk_types": kb.get("chunk_types"),
        },
    }


def list_users() -> list[dict[str, Any]]:
    with conn() as con:
        rows = con.execute(
            """
            SELECT u.username, u.is_admin, u.created_at,
                   (SELECT COUNT(*) FROM conversations c WHERE c.username = u.username) AS conversations,
                   (SELECT COUNT(*) FROM messages m WHERE m.username = u.username AND m.role = 'user') AS questions,
                   (SELECT MAX(created_at) FROM messages m WHERE m.username = u.username) AS last_at
            FROM users u
            ORDER BY CASE WHEN last_at IS NULL THEN 1 ELSE 0 END, last_at DESC, u.created_at DESC
            """
        ).fetchall()
    return _rows(rows)


def list_feedback(limit: int = 80) -> list[dict[str, Any]]:
    with conn() as con:
        rows = con.execute(
            """
            SELECT f.id, f.rating, f.comment, f.created_at, f.username,
                   a.content AS answer, q.content AS question, a.intent,
                   a.citations
            FROM feedback f
            JOIN messages a ON a.id = f.message_id
            LEFT JOIN messages q ON q.id = (
                SELECT MAX(id) FROM messages
                WHERE conversation_id = a.conversation_id AND role = 'user' AND id < a.id
            )
            ORDER BY f.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    out = []
    for r in rows:
        rec = dict(r)
        try:
            rec["citations"] = json.loads(rec.get("citations") or "[]")
        except json.JSONDecodeError:
            rec["citations"] = []
        rec["answer"] = (rec.get("answer") or "")[:400]
        rec["question"] = rec.get("question") or ""
        out.append(rec)
    return out


def similar_user_feedback(question: str) -> dict[str, Any]:
    q = question.strip()
    key = q[:18]
    with conn() as con:
        rows = con.execute(
            """
            SELECT f.rating
            FROM feedback f
            JOIN messages a ON a.id = f.message_id
            JOIN messages u ON u.conversation_id = a.conversation_id AND u.role = 'user'
                 AND u.id = (SELECT MAX(id) FROM messages
                             WHERE conversation_id = a.conversation_id AND role = 'user' AND id < a.id)
            WHERE u.content LIKE ?
            """,
            (f"%{key}%",),
        ).fetchall()
    good = sum(1 for r in rows if r["rating"] == 1)
    bad = sum(1 for r in rows if r["rating"] == -1)
    n = good + bad
    return {"n": n, "good": good, "bad": bad, "good_rate": (good / n) if n else None}


def save_eval_run(payload: dict[str, Any]) -> int:
    with conn() as con:
        cur = con.execute(
            """
            INSERT INTO eval_runs (started_at, finished_at, n, recall_at_k, mrr, citation_hit, detail)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["started_at"],
                payload["finished_at"],
                payload["n"],
                payload["recall_at_k"],
                payload["mrr"],
                payload["citation_hit"],
                json.dumps(payload["detail"], ensure_ascii=False),
            ),
        )
        return int(cur.lastrowid)


def latest_eval() -> dict[str, Any] | None:
    with conn() as con:
        row = con.execute("SELECT * FROM eval_runs ORDER BY id DESC LIMIT 1").fetchone()
    if not row:
        return None
    rec = dict(row)
    rec["detail"] = json.loads(rec["detail"])
    return rec
