# -*- coding: utf-8 -*-
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from law_rag.offline.chunker import process_all


if __name__ == "__main__":
    stats = process_all()
    print(json.dumps(stats, ensure_ascii=False, indent=2))
