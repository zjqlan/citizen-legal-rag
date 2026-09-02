# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from typing import Any, Iterable

from pymilvus import DataType, MilvusClient

from law_rag import settings as S
from law_rag.encoding import Embedder, lexical_to_sparse

INDEX_TYPES = {"article", "child", "window"}


def _iter_index_chunks() -> Iterable[dict[str, Any]]:
    with S.CHUNKS_PATH.open(encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            if rec.get("chunk_type") in INDEX_TYPES:
                yield rec


def _parent_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    with S.CHUNKS_PATH.open(encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            if rec.get("chunk_type") == "parent":
                mapping[rec["chunk_id"]] = rec["text"]
    return mapping


def ingest(limit: int | None = None) -> dict[str, Any]:
    chunks = list(_iter_index_chunks())
    if limit:
        chunks = chunks[:limit]
    parents = _parent_map()
    embedder = Embedder()
    client = MilvusClient(S.MILVUS_URI)
    if client.has_collection(S.MILVUS_COLLECTION):
        client.drop_collection(S.MILVUS_COLLECTION)

    schema = client.create_schema(auto_id=False, enable_dynamic_field=True)
    schema.add_field("chunk_id", DataType.VARCHAR, is_primary=True, max_length=64)
    schema.add_field("doc_id", DataType.VARCHAR, max_length=80)
    schema.add_field("law_name", DataType.VARCHAR, max_length=256)
    schema.add_field("article", DataType.VARCHAR, max_length=64)
    schema.add_field("doc_type", DataType.VARCHAR, max_length=32)
    schema.add_field("status", DataType.VARCHAR, max_length=16)
    schema.add_field("region", DataType.VARCHAR, max_length=32)
    schema.add_field("chunk_type", DataType.VARCHAR, max_length=16)
    schema.add_field("parent_id", DataType.VARCHAR, max_length=64)
    schema.add_field("text", DataType.VARCHAR, max_length=65535)
    schema.add_field("parent_text", DataType.VARCHAR, max_length=65535)
    schema.add_field("dense", DataType.FLOAT_VECTOR, dim=S.DENSE_DIM)
    schema.add_field("sparse", DataType.SPARSE_FLOAT_VECTOR)

    index_params = client.prepare_index_params()
    index_params.add_index(
        field_name="dense",
        index_type="IVF_FLAT",
        metric_type="COSINE",
        params={"nlist": 1024},
    )
    index_params.add_index(
        field_name="sparse",
        index_type="SPARSE_INVERTED_INDEX",
        metric_type="IP",
        params={"drop_ratio_build": 0.2},
    )
    client.create_collection(
        collection_name=S.MILVUS_COLLECTION,
        schema=schema,
        index_params=index_params,
    )

    total = len(chunks)
    inserted = 0
    batch_n = S.ENCODE_BATCH
    for start in range(0, total, batch_n):
        batch = chunks[start : start + batch_n]
        texts = [c["text"][: S.TEXT_MAX] for c in batch]
        out = embedder.encode(texts)
        dense = out["dense_vecs"]
        sparse_w = out["lexical_weights"]
        payload = []
        for i, c in enumerate(batch):
            vec = dense[i]
            if hasattr(vec, "tolist"):
                vec = vec.tolist()
            pid = c.get("parent_id") or ""
            parent_text = parents.get(pid, "") if pid else c["text"]
            payload.append(
                {
                    "chunk_id": c["chunk_id"][:64],
                    "doc_id": (c.get("doc_id") or "")[:80],
                    "law_name": (c.get("law_name") or "")[:256],
                    "article": (c.get("article") or "")[:64],
                    "doc_type": (c.get("doc_type") or "")[:32],
                    "status": (c.get("status") or "")[:16],
                    "region": (c.get("region") or "全国")[:32],
                    "chunk_type": (c.get("chunk_type") or "")[:16],
                    "parent_id": pid[:64],
                    "text": c["text"][:65535],
                    "parent_text": (parent_text or c["text"])[:65535],
                    "dense": vec,
                    "sparse": lexical_to_sparse(sparse_w[i]),
                }
            )
        client.insert(S.MILVUS_COLLECTION, payload)
        inserted += len(payload)
        print(f"  已写入 {inserted}/{total}", flush=True)

    client.flush(S.MILVUS_COLLECTION)
    client.load_collection(S.MILVUS_COLLECTION)
    meta = {
        "collection": S.MILVUS_COLLECTION,
        "uri": S.MILVUS_URI,
        "rows": inserted,
        "encoder": S._rel(S.BGE_M3_PATH),
    }
    (S.ROOT / "data" / "kb").mkdir(parents=True, exist_ok=True)
    (S.ROOT / "data" / "kb" / "kb_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return meta
