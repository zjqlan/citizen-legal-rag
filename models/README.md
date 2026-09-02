# 本地检索 / 重排模型

将以下模型放到本目录（或在 `.env` 里把 `MODEL_ROOT` 指到已有目录）：

```
models/
  bge-m3/
  bge-reranker-v2-m3/
```

可从 Hugging Face 下载：

- https://huggingface.co/BAAI/bge-m3
- https://huggingface.co/BAAI/bge-reranker-v2-m3

示例：

```bash
pip install huggingface_hub
huggingface-cli download BAAI/bge-m3 --local-dir models/bge-m3
huggingface-cli download BAAI/bge-reranker-v2-m3 --local-dir models/bge-reranker-v2-m3
```
