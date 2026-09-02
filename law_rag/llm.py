# -*- coding: utf-8 -*-
from __future__ import annotations

from collections.abc import Iterator

from openai import OpenAI

from law_rag import settings as S


def get_client() -> OpenAI:
    if not S.LLM_API_KEY:
        raise RuntimeError("未配置 LLM_API_KEY，请在项目根目录 .env 中填写。")
    return OpenAI(api_key=S.LLM_API_KEY, base_url=S.LLM_BASE_URL)


def chat(messages: list[dict], temperature: float = 0.2, max_tokens: int = 1200) -> str:
    return "".join(chat_stream(messages, temperature=temperature, max_tokens=max_tokens))


def chat_stream(
    messages: list[dict],
    temperature: float = 0.2,
    max_tokens: int = 1200,
) -> Iterator[str]:
    client = get_client()
    stream = client.chat.completions.create(
        model=S.LLM_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
    )
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        text = getattr(delta, "content", None)
        if text:
            yield text
