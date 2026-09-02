# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

from pymilvus import AnnSearchRequest, MilvusClient, RRFRanker
from sentence_transformers import CrossEncoder

from law_rag import settings as S
from law_rag.encoding import Embedder, lexical_to_sparse


class Retriever:
    def __init__(self) -> None:
        self.client = MilvusClient(S.MILVUS_URI)
        if not self.client.has_collection(S.MILVUS_COLLECTION):
            raise RuntimeError(
                f"集合 {S.MILVUS_COLLECTION} 不存在，请先运行 python scripts/ingest_kb.py"
            )
        self.client.load_collection(S.MILVUS_COLLECTION)
        self.embedder = Embedder()
        self.reranker = CrossEncoder(str(S.BGE_RERANKER_PATH))

    def search(self, query: str, status: str = "有效") -> list[dict[str, Any]]:
        out = self.embedder.encode([query])
        dense = out["dense_vecs"][0]
        if hasattr(dense, "tolist"):
            dense = dense.tolist()
        sparse = lexical_to_sparse(out["lexical_weights"][0])
        expr = f'status == "{status}"' if status else ""
        k = S.RECALL_K
        dense_req = AnnSearchRequest(
            data=[dense],
            anns_field="dense",
            param={"metric_type": "COSINE", "params": {"nprobe": 32}},
            limit=k,
            expr=expr,
        )
        sparse_req = AnnSearchRequest(
            data=[sparse],
            anns_field="sparse",
            param={"metric_type": "IP", "params": {}},
            limit=k,
            expr=expr,
        )
        hits = self.client.hybrid_search(
            collection_name=S.MILVUS_COLLECTION,
            reqs=[dense_req, sparse_req],
            ranker=RRFRanker(k=60),
            limit=k,
            output_fields=[
                "chunk_id",
                "law_name",
                "article",
                "doc_type",
                "status",
                "text",
                "parent_text",
                "parent_id",
            ],
        )[0]
        docs = []
        seen = set()
        for hit in hits:
            ent = hit["entity"] if isinstance(hit, dict) else getattr(hit, "entity", {})
            if hasattr(ent, "get"):
                data = ent
            else:
                data = dict(ent)
            key = data.get("parent_id") or data.get("chunk_id")
            if key in seen:
                continue
            seen.add(key)
            body = data.get("parent_text") or data.get("text") or ""
            dist = hit.get("distance") if isinstance(hit, dict) else getattr(hit, "distance", 0)
            docs.append(
                {
                    "chunk_id": data.get("chunk_id"),
                    "law_name": data.get("law_name"),
                    "article": data.get("article"),
                    "doc_type": data.get("doc_type"),
                    "status": data.get("status"),
                    "text": body,
                    "score": float(dist or 0),
                }
            )
        if not docs:
            return []
        pairs = [[query, d["text"][:4000]] for d in docs]
        scores = self.reranker.predict(pairs)
        ranked = [
            {**d, "rerank": float(s)}
            for d, s in sorted(zip(docs, scores), key=lambda x: x[1], reverse=True)
        ]
        return ranked[: S.RERANK_TOPK]
