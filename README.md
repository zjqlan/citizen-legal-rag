# 百姓普法助手

面向劳动、租房、消费、婚姻家庭等日常场景的法律法规 RAG 问答。法律咨询一律检索知识库，生成只依据召回条文并附《法律名称》+ 条号；检索为空则明确说明不能确定。

本仓库提供可复现的离线建库与在线问答链路，**不提供律师意见**。法规原文体积较大，不进 git，需本地采集或自行准备。

## 链路

```
采集全国人大公开库
    → 按「条」分块（超长条按款做父子块）
    → BGE-M3 稠密 + 稀疏写入 Milvus
    → 意图分流 / 问题改写
    → 双路召回 → RRF → BGE-Reranker Top8
    → 通义千问流式生成（强制引用）
```

当前知识库规模（本地跑完采集与分块后）：548 部现行全国性法规（宪法 7、法律 342、行政法规 78、司法解释 121），约 3.1 万检索块。行政法规与司法解释按高频场景过滤，不含地方性法规。

检索评测：`data/eval/gold.jsonl` 中 12 道高频标注题，按法名 + 条号看 Top8 是否命中（Hit Rate / MRR）。题量小，不作全库效果宣传。

## 环境

- Python 3.10+
- [Milvus](https://milvus.io/) 2.4+（默认连接本机 19530 端口）
- DashScope / 通义千问 API Key
- 本地模型目录（见 `models/README.md`）
  - `BAAI/bge-m3`
  - `BAAI/bge-reranker-v2-m3`

Milvus standalone 可用官方 compose：

```bash
# 示例：https://milvus.io/docs/install_standalone-docker.md
docker compose up -d
```

## 运行

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
pip install -r requirements.txt

copy .env.example .env
# 编辑 .env：填写 LLM_API_KEY、ADMIN_PASSWORD，并确认 MODEL_ROOT
```

`.env` 必填：

| 变量 | 说明 |
|------|------|
| `LLM_API_KEY` | 通义千问 / DashScope Key |
| `MODEL_ROOT` | 本地 BGE 模型根目录，默认 `./models` |
| `ADMIN_PASSWORD` | 管理后台账号密码（用户名默认 `admin`） |
| `SESSION_SECRET` | 会话签名，请改成随机串 |

然后：

```bash
python scripts/crawl_flk_npc.py    # 采集公开法规（耗时较长，可跳过若已有 data/raw）
python scripts/process_data.py     # 按条分块
python scripts/ingest_kb.py        # 写入 Milvus
python app.py                      # 启动问答服务（默认端口 8010）
```

启动后在浏览器打开问答页，管理后台路径为 `/admin`。命令行调试：`python scripts/chat.py`。试跑入库可用 `python scripts/ingest_kb.py --limit 200`。

## 目录

```
├── app.py / static/          # FastAPI 问答页与管理后台
├── law_rag/                  # 离线分块入库、在线分流 / 改写 / 检索 / 生成
├── scripts/crawl_flk_npc.py  # 全国人大法规公开库采集
├── scripts/process_data.py
├── scripts/ingest_kb.py
├── data/eval/gold.jsonl      # 12 道检索评测题
├── data/processed/stats.json # 分块统计（法规原文不进仓库）
└── docs/                     # 背景、链路设计、流程图
```

## 技术要点

BGE-M3 稠密/稀疏双路 → Milvus hybrid search → RRF → BGE-Reranker-v2-m3 → 通义千问 SSE 流式生成。约束生成不能从程序上保证零幻觉，需结合出处人工核对。

## 许可

代码为 MIT。法规文本来自国家法律法规数据库公开内容，使用时请遵守其网站条款。本项目仅供普法学习与技术演示。
