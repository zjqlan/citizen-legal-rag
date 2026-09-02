# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

from law_rag import settings as S
from law_rag.auth import (
    authenticate,
    create_user,
    init_users,
    make_captcha,
    validate_password,
    validate_username,
    verify_captcha,
)
from law_rag.eval_gold import hit_rank, load_gold
from law_rag.store import (
    chunk_stats,
    chunks_status,
    ensure_chunk_index,
    get_chunk,
    get_conversation,
    is_admin,
    latest_eval,
    list_conversations,
    list_feedback,
    list_users,
    overview,
    save_eval_run,
    save_feedback,
    save_turn,
    search_chunks,
    similar_user_feedback,
)

STATIC_DIR = ROOT / "static"
qa = None
load_error: str | None = None
ready = False


def _load_engine() -> None:
    global qa, ready, load_error
    try:
        from law_rag.online.pipeline import LawQA

        qa = LawQA()
        ready = True
    except Exception as exc:
        load_error = str(exc)
        ready = False


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_users()
    threading.Thread(target=ensure_chunk_index, daemon=True).start()
    threading.Thread(target=_load_engine, daemon=True).start()
    yield


app = FastAPI(
    title="百姓普法助手",
    description="面向普通百姓的法律法规问答接口。依据为国家现行法律、行政法规与司法解释。",
    lifespan=lifespan,
)
app.add_middleware(
    SessionMiddleware,
    secret_key=S.SESSION_SECRET,
    session_cookie="law_session",
    same_site="lax",
    https_only=False,
    max_age=7 * 24 * 3600,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8010", "http://localhost:8010"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class HistoryTurn(BaseModel):
    role: str
    content: str


class AskIn(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    history: list[HistoryTurn] | None = None
    session_id: str | None = None
    conversation_id: str | None = None


class AskOut(BaseModel):
    intent: str
    answer: str
    citations: list[dict] = []
    queries: list[str] = []
    notes: str = ""
    conversation_id: str = ""
    message_id: int | None = None


class AuthIn(BaseModel):
    username: str = Field(..., min_length=1, max_length=20)
    password: str = Field(..., min_length=1, max_length=64)
    captcha_id: str
    captcha: str


class FeedbackIn(BaseModel):
    message_id: int
    rating: int
    comment: str = ""


def current_user(request: Request) -> str | None:
    user = request.session.get("user")
    return user if isinstance(user, str) and user else None


def require_user(request: Request) -> str:
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    return user


def require_admin(request: Request) -> str:
    user = require_user(request)
    if not request.session.get("admin") and not is_admin(user):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def _login_session(request: Request, username: str) -> dict:
    request.session.clear()
    request.session["user"] = username
    admin = is_admin(username)
    request.session["admin"] = admin
    return {"ok": True, "username": username, "is_admin": admin}


@app.get("/api/health")
def health():
    return {
        "ok": ready,
        "error": load_error,
        "collection": S.MILVUS_COLLECTION,
        "model": S.LLM_MODEL,
        "chunks_index": chunks_status(),
    }


@app.get("/api/meta")
def meta():
    stats = {}
    if S.STATS_PATH.exists():
        stats = json.loads(S.STATS_PATH.read_text(encoding="utf-8"))
    return {
        "name": "百姓普法助手",
        "scope": "国家现行法律、行政法规、司法解释（不含地方性法规）",
        "disclaimer": "本服务仅供普法参考，不构成律师意见或行政机关答复。",
        "hotline": "12348",
        "stats": {
            "documents": stats.get("documents"),
            "chunks": stats.get("chunks"),
            "doc_types": stats.get("doc_types"),
        },
    }


@app.get("/api/auth/captcha")
def auth_captcha():
    captcha_id, svg = make_captcha()
    return {"captcha_id": captcha_id, "svg": svg}


@app.get("/api/auth/me")
def auth_me(request: Request):
    user = current_user(request)
    admin = bool(request.session.get("admin")) if user else False
    if user and not admin:
        admin = is_admin(user)
        request.session["admin"] = admin
    return {"ok": bool(user), "username": user, "is_admin": admin}


@app.post("/api/auth/register")
def auth_register(request: Request, body: AuthIn):
    if not verify_captcha(body.captcha_id, body.captcha):
        raise HTTPException(status_code=400, detail="验证码错误或已过期，请刷新后重试")
    try:
        username = validate_username(body.username)
        password = validate_password(body.password)
        create_user(username, password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _login_session(request, username)


@app.post("/api/auth/login")
def auth_login(request: Request, body: AuthIn):
    if not verify_captcha(body.captcha_id, body.captcha):
        raise HTTPException(status_code=400, detail="验证码错误或已过期，请刷新后重试")
    try:
        username = validate_username(body.username)
        password = validate_password(body.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not authenticate(username, password):
        raise HTTPException(status_code=400, detail="用户名或密码不正确")
    return _login_session(request, username)


@app.post("/api/auth/logout")
def auth_logout(request: Request):
    request.session.clear()
    return {"ok": True}


@app.get("/api/chats")
def api_chats(request: Request):
    user = require_user(request)
    return {"items": list_conversations(user)}


@app.get("/api/chats/{conv_id}")
def api_chat_detail(request: Request, conv_id: str):
    user = require_user(request)
    item = get_conversation(user, conv_id)
    if not item:
        raise HTTPException(status_code=404, detail="对话不存在")
    return item


@app.post("/api/feedback")
def api_feedback(request: Request, body: FeedbackIn):
    user = require_user(request)
    try:
        save_feedback(user, body.message_id, body.rating, body.comment)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@app.post("/api/ask", response_model=AskOut)
def ask(request: Request, body: AskIn):
    user = require_user(request)
    if not ready or qa is None:
        raise HTTPException(status_code=503, detail=load_error or "知识库正在加载，请稍候再试")
    history = [t.model_dump() for t in (body.history or [])]
    t0 = time.time()
    result = qa.ask(body.question.strip(), history, session_id=f"user:{user}")
    saved = save_turn(
        username=user,
        conversation_id=body.conversation_id,
        question=body.question.strip(),
        answer=result.get("answer") or "",
        intent=result.get("intent") or "",
        citations=result.get("citations") or [],
        retrieved=[],
        queries=result.get("queries") or [],
        latency_ms=(time.time() - t0) * 1000,
    )
    return {
        "intent": result.get("intent") or "legal",
        "answer": result.get("answer") or "",
        "citations": result.get("citations") or [],
        "queries": result.get("queries") or [],
        "notes": result.get("notes") or "",
        "conversation_id": saved["conversation_id"],
        "message_id": saved["message_id"],
    }


@app.post("/api/ask/stream")
def ask_stream(request: Request, body: AskIn):
    user = require_user(request)
    if not ready or qa is None:
        raise HTTPException(status_code=503, detail=load_error or "知识库正在加载，请稍候再试")
    history = [t.model_dump() for t in (body.history or [])]

    def events():
        t0 = time.time()
        acc: list[str] = []
        meta: dict = {}
        cites: list = []
        retrieved: list = []
        for ev in qa.ask_stream(body.question.strip(), history, session_id=f"user:{user}"):
            if ev.get("event") == "meta":
                meta = ev
            elif ev.get("event") == "delta":
                acc.append(ev.get("text") or "")
            elif ev.get("event") == "citations":
                cites = ev.get("citations") or []
            elif ev.get("event") == "retrieved":
                retrieved = ev.get("passages") or []
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        saved = save_turn(
            username=user,
            conversation_id=body.conversation_id,
            question=body.question.strip(),
            answer="".join(acc),
            intent=meta.get("intent") or "",
            citations=cites,
            retrieved=retrieved,
            queries=meta.get("queries") or [],
            latency_ms=(time.time() - t0) * 1000,
        )
        yield f"data: {json.dumps({'event': 'saved', **saved}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/admin/overview")
def admin_overview(request: Request):
    require_admin(request)
    data = overview()
    data["pipeline"] = {
        "offline": ["法规解析", "按条分块", "BGE-M3 稠密+稀疏", "写入 Milvus"],
        "online": ["登录校验", "意图分流", "问题改写", "双路召回+RRF", "重排序", "依据条文生成"],
        "scope": "国家现行法律、行政法规、司法解释（不含地方性法规）",
        "models": {"embed": "bge-m3", "rerank": "bge-reranker-v2-m3", "llm": S.LLM_MODEL},
    }
    return data


@app.get("/api/admin/chunks")
def admin_chunks(
    request: Request,
    q: str = "",
    doc_type: str = "",
    chunk_type: str = "",
    page: int = 1,
):
    require_admin(request)
    return {"stats": chunk_stats(), **search_chunks(q, doc_type, chunk_type, page)}


@app.get("/api/admin/chunks/{chunk_id}")
def admin_chunk_detail(request: Request, chunk_id: str):
    require_admin(request)
    item = get_chunk(chunk_id)
    if not item:
        raise HTTPException(status_code=404, detail="分块不存在")
    return item


@app.get("/api/admin/users")
def admin_users(request: Request):
    require_admin(request)
    return {"items": list_users()}


@app.get("/api/admin/feedback")
def admin_feedback(request: Request):
    require_admin(request)
    return {"items": list_feedback()}


@app.get("/api/admin/eval")
def admin_eval(request: Request):
    require_admin(request)
    return {"gold": load_gold(), "latest": latest_eval()}


@app.post("/api/admin/eval/run")
def admin_eval_run(request: Request):
    require_admin(request)
    if not ready or qa is None:
        raise HTTPException(status_code=503, detail=load_error or "检索引擎尚未就绪")
    gold = load_gold()
    if not gold:
        raise HTTPException(status_code=400, detail="没有测试题，请检查 data/eval/gold.jsonl")
    started = time.time()
    detail = []
    hits = 0
    mrr_sum = 0.0
    for case in gold:
        passages, queries, _notes = qa.retrieve_passages(case["question"], [], use_rewrite=False)
        rank = hit_rank(case.get("gold") or [], passages)
        ok = rank is not None
        hits += int(ok)
        mrr_sum += (1.0 / rank) if rank else 0.0
        fb = similar_user_feedback(case["question"])
        detail.append(
            {
                "question": case["question"],
                "topic": case.get("topic") or "",
                "gold": case.get("gold") or [],
                "hit": ok,
                "rank": rank,
                "queries": queries,
                "retrieved": [
                    {
                        "law_name": p.get("law_name"),
                        "article": p.get("article"),
                        "rerank": round(float(p.get("rerank") or 0), 3),
                    }
                    for p in passages[:6]
                ],
                "user_feedback": fb,
            }
        )
    n = len(gold)
    payload = {
        "started_at": started,
        "finished_at": time.time(),
        "n": n,
        "recall_at_k": hits / n if n else 0,
        "mrr": mrr_sum / n if n else 0,
        "citation_hit": hits / n if n else 0,
        "detail": detail,
    }
    payload["id"] = save_eval_run(payload)
    return payload


@app.get("/")
def index():
    return FileResponse(
        STATIC_DIR / "index.html",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/admin")
def admin_page():
    return FileResponse(
        STATIC_DIR / "admin.html",
        headers={"Cache-Control": "no-store"},
    )


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="127.0.0.1", port=8010, reload=False)
