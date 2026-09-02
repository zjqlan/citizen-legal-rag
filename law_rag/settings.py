# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.name


RAW_TEXT_DIR = ROOT / "data" / "raw" / "npc" / "texts"
RAW_MANIFEST = ROOT / "data" / "raw" / "npc" / "manifest.jsonl"
PROCESSED_DIR = ROOT / "data" / "processed"
DOCUMENTS_PATH = PROCESSED_DIR / "documents.jsonl"
CHUNKS_PATH = PROCESSED_DIR / "chunks.jsonl"
STATS_PATH = PROCESSED_DIR / "stats.json"

MODEL_ROOT = Path(os.getenv("MODEL_ROOT", str(ROOT / "models")))
BGE_M3_PATH = Path(os.getenv("BGE_M3_PATH", str(MODEL_ROOT / "bge-m3")))
BGE_RERANKER_PATH = Path(
    os.getenv("BGE_RERANKER_PATH", str(MODEL_ROOT / "bge-reranker-v2-m3"))
)

MILVUS_URI = os.getenv("MILVUS_URI", "http://127.0.0.1:19530")
MILVUS_COLLECTION = os.getenv("MILVUS_COLLECTION", "law_chunks")

LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv(
    "LLM_BASE_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
)
LLM_MODEL = os.getenv("LLM_MODEL", "qwen-plus")

DENSE_DIM = 1024
RECALL_K = int(os.getenv("RECALL_K", "30"))
RERANK_TOPK = int(os.getenv("RERANK_TOPK", "8"))
LONG_ARTICLE_CHARS = 1200
WINDOW_SIZE = 400
WINDOW_OVERLAP = 64
TEXT_MAX = 60000
ENCODE_BATCH = int(os.getenv("ENCODE_BATCH", "8"))
ENCODE_MAX_LEN = 1024

USER_DB = Path(os.getenv("USER_DB", str(ROOT / "data" / "users.db")))
SESSION_SECRET = os.getenv("SESSION_SECRET", "change-this-in-production")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
GOLD_PATH = Path(os.getenv("GOLD_PATH", str(ROOT / "data" / "eval" / "gold.jsonl")))
