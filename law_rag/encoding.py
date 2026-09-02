# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

from law_rag import settings as S


class Embedder:
    def __init__(self) -> None:
        import torch
        from FlagEmbedding import BGEM3FlagModel

        device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = device
        self.model = BGEM3FlagModel(
            str(S.BGE_M3_PATH),
            use_fp16=device == "cuda",
            device=device,
        )

    def encode(self, texts: list[str]) -> dict[str, Any]:
        return self.model.encode(
            texts,
            batch_size=len(texts),
            max_length=S.ENCODE_MAX_LEN,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False,
        )


def lexical_to_sparse(lexical_weights: dict) -> dict[int, float]:
    out: dict[int, float] = {}
    for token, weight in lexical_weights.items():
        if isinstance(token, int):
            idx = token
        elif str(token).isdigit():
            idx = int(token)
        else:
            idx = abs(hash(str(token))) % (2**31 - 1)
        out[idx] = float(weight)
    return out
