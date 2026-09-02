# -*- coding: utf-8 -*-
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from law_rag.offline.ingest import ingest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="仅入库前 N 条，便于试跑")
    args = parser.parse_args()
    meta = ingest(limit=args.limit or None)
    print(json.dumps(meta, ensure_ascii=False, indent=2))
