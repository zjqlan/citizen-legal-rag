# -*- coding: utf-8 -*-
from __future__ import annotations

import re

CHAT_PAT = re.compile(
    r"^(你好|您好|在吗|谢谢|感谢|早上好|晚上好|嗨|哈喽|hello|hi)[\s!！。.?？]*$",
    re.I,
)
EMOTION_PAT = re.compile(r"(我好难过|我好伤心|我好愤怒|我好累|心情不好|想哭)")
FOLLOWUP_PAT = re.compile(
    r"^(那|然后|还有|这个|刚才|继续|怎么办|怎么算|还要|能要|可以吗|是吗|对吗)"
)
LEGAL_HINT = re.compile(
    r"(法|条|合同|劳动|工资|辞退|开除|赔偿|补偿|起诉|仲裁|租|押金|消费|退货|"
    r"离婚|抚养|赡养|交通|工伤|社保|物业|侵权|诉讼|时效|公司|用人单位|"
    r"加班|试用|借款|欠钱|家暴|逃逸|广告|未成年|七天|无理由)"
)
REFUSE_PAT = re.compile(r"(怎么造假|如何逃税且不被发现|教我犯罪|如何杀人)")


def classify(question: str, history: list[dict] | None = None) -> str:
    q = (question or "").strip()
    if not q or len(q) < 2:
        return "empty"
    if REFUSE_PAT.search(q):
        return "refuse"
    if CHAT_PAT.match(q) or (EMOTION_PAT.search(q) and not LEGAL_HINT.search(q)):
        return "chitchat"
    if history and FOLLOWUP_PAT.search(q):
        return "legal"
    if LEGAL_HINT.search(q) or len(q) >= 8:
        return "legal"
    return "chitchat"
