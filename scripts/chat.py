# -*- coding: utf-8 -*-
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from law_rag.online.pipeline import LawQA


def main() -> None:
    print("法律法规问答助手。输入 exit 退出。")
    qa = LawQA()
    history: list[dict] = []
    while True:
        q = input("\n你：").strip()
        if q.lower() in {"exit", "quit", "q"}:
            break
        out = qa.ask(q, history)
        print("\n助手：")
        print(out["answer"])
        history.append({"role": "user", "content": q})
        history.append({"role": "assistant", "content": out["answer"]})
        history = history[-8:]


if __name__ == "__main__":
    main()
