# -*- coding: utf-8 -*-
"""采集国家法律法规数据库（flk.npc.gov.cn）公开文本，供 RAG 知识库使用。"""
from __future__ import annotations

import json
import re
import time
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "raw" / "npc"
TEXT_DIR = DATA_DIR / "texts"
FILE_DIR = DATA_DIR / "files"
META_PATH = DATA_DIR / "manifest.jsonl"
CHECKPOINT = DATA_DIR / "_checkpoint.json"

BASE = "https://flk.npc.gov.cn"
LIST_URL = f"{BASE}/law-search/search/list"
DETAIL_URL = f"{BASE}/law-search/search/flfgDetails"
DOWNLOAD_URL = f"{BASE}/law-search/download/mobile"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json;charset=utf-8",
    "Referer": f"{BASE}/",
    "Origin": BASE,
}

# 叶子分类：父级 code 查不到数据。不采集地方性法规。
CATEGORIES: list[tuple[str, list[int], str]] = [
    ("宪法", [100], "all"),
    (
        "法律",
        [110, 120, 130, 140, 150, 155, 160, 170, 180, 190, 195, 200],
        "all",
    ),
    ("行政法规", [210], "keyword"),
    ("司法解释", [320, 330, 340], "keyword"),
]

CITIZEN_KEYWORDS = (
    "劳动",
    "合同",
    "消费",
    "婚姻",
    "家庭",
    "继承",
    "交通",
    "工伤",
    "失业",
    "社会保险",
    "社保",
    "物业",
    "房屋",
    "租赁",
    "房地产",
    "食品安全",
    "产品质量",
    "治安",
    "诉讼",
    "电子商务",
    "个人信息",
    "未成年人",
    "妇女",
    "老年人",
    "反家庭暴力",
    "医疗",
    "教育",
    "广告",
    "价格",
    "旅游",
    "快递",
    "网络",
    "侵权",
    "人格",
    "土地",
    "村民",
    "保险",
    "行政处罚",
    "行政复议",
    "国家赔偿",
    "安全生产",
    "环境保护",
    "噪声",
    "物业管理",
    "城市房地产",
    "预付",
    "民办教育",
    "道路",
    "车辆",
    "工伤保险",
    "失业保险",
    "医疗保障",
    "基本医疗卫生",
    "消费者",
)

SXX_KEEP = {3, 4}  # 有效、尚未施行
SXX_NAME = {1: "已废止", 2: "已修改", 3: "有效", 4: "尚未施行"}
PAGE_SIZE = 20
SLEEP = 0.35
TIMEOUT = 60


def safe_name(title: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]', "_", (title or "").strip())
    name = re.sub(r"\s+", " ", name)
    return (name[:110] or "untitled").rstrip(". ")


def docx_to_text(blob: bytes) -> str:
    with zipfile.ZipFile(BytesIO(blob)) as zf:
        xml = zf.read("word/document.xml")
    root = ET.fromstring(xml)
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paras: list[str] = []
    for p in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
        texts = [t.text or "" for t in p.findall(".//w:t", ns)]
        line = "".join(texts).strip()
        if line:
            paras.append(line)
    return "\n".join(paras)


def need_title(mode: str, title: str) -> bool:
    if mode == "all":
        return True
    return any(k in title for k in CITIZEN_KEYWORDS)


def load_checkpoint() -> set[str]:
    if CHECKPOINT.exists():
        data = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
        return set(data.get("done_ids", []))
    return set()


def save_checkpoint(done: set[str]) -> None:
    CHECKPOINT.write_text(
        json.dumps({"done_ids": sorted(done)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def list_page(session: requests.Session, code_ids: list[int], page_num: int) -> dict[str, Any]:
    payload = {
        "searchRange": 1,
        "sxrq": [],
        "gbrq": [],
        "searchType": 2,
        "sxx": [3, 4],
        "gbrqYear": [],
        "flfgCodeId": code_ids,
        "zdjgCodeId": [],
        "searchContent": "",
        "pageNum": page_num,
        "pageSize": PAGE_SIZE,
    }
    r = session.post(LIST_URL, json=payload, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def _looks_json(blob: bytes) -> bool:
    stripped = blob.lstrip()
    return stripped.startswith(b"{") or stripped.startswith(b"[")


def download_docx(session: requests.Session, bbbs: str) -> tuple[bytes, str]:
    """返回 (文件字节, 扩展名)。优先 docx，失败则尝试 pdf。"""
    r = session.get(
        DOWNLOAD_URL,
        params={"format": "docx", "bbbs": bbbs, "fileId": ""},
        timeout=TIMEOUT,
        headers={"Accept": "*/*"},
    )
    r.raise_for_status()
    blob = r.content
    if blob[:2] == b"PK":
        return blob, "docx"
    if blob[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return blob, "doc"
    if _looks_json(blob):
        payload = r.json()
        url = ((payload.get("data") or {}).get("url") or "").strip()
        if url:
            f = session.get(url, timeout=TIMEOUT, headers={"Accept": "*/*"})
            f.raise_for_status()
            if f.content[:2] == b"PK":
                return f.content, "docx"
            if f.content[:4] == b"%PDF":
                return f.content, "pdf"
    r2 = session.get(
        DOWNLOAD_URL,
        params={"format": "pdf", "bbbs": bbbs, "fileId": ""},
        timeout=TIMEOUT,
        headers={"Accept": "*/*"},
    )
    r2.raise_for_status()
    if r2.content[:4] == b"%PDF":
        return r2.content, "pdf"
    if r2.content[:2] == b"PK":
        return r2.content, "docx"
    raise RuntimeError(f"无法下载正文，content-type={r.headers.get('content-type')} len={len(blob)}")


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    TEXT_DIR.mkdir(exist_ok=True)
    FILE_DIR.mkdir(exist_ok=True)

    done = load_checkpoint()
    session = requests.Session()
    session.headers.update(HEADERS)
    saved = 0
    skipped = 0

    with META_PATH.open("a", encoding="utf-8") as manifest:
        for type_name, code_ids, mode in CATEGORIES:
            first = list_page(session, code_ids, 1)
            time.sleep(SLEEP)
            total = int(first.get("total") or 0)
            pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
            print(f"[{type_name}] 现行/未施行约 {total} 条，{pages} 页，模式={mode}", flush=True)
            for page in range(1, pages + 1):
                payload = first if page == 1 else list_page(session, code_ids, page)
                if page > 1:
                    time.sleep(SLEEP)
                rows = payload.get("rows") or []
                for row in rows:
                    bbbs = row.get("bbbs")
                    title = (row.get("title") or "").strip()
                    sxx = row.get("sxx")
                    if not bbbs:
                        continue
                    if bbbs in done:
                        skipped += 1
                        continue
                    if sxx not in SXX_KEEP:
                        done.add(bbbs)
                        continue
                    if not need_title(mode, title):
                        done.add(bbbs)
                        continue
                    try:
                        blob, ext = download_docx(session, bbbs)
                        time.sleep(SLEEP)
                    except Exception as exc:
                        print(f"  下载失败 {title}: {exc!s}".encode("gbk", "replace").decode("gbk"), flush=True)
                        time.sleep(SLEEP)
                        continue
                    text = ""
                    if ext == "docx":
                        try:
                            text = docx_to_text(blob)
                        except Exception as exc:
                            print(f"  解析失败 {title}: {exc!s}".encode("gbk", "replace").decode("gbk"), flush=True)
                    fname = f"{safe_name(title)}_{bbbs[-8:]}"
                    (FILE_DIR / f"{fname}.{ext}").write_bytes(blob)
                    rec = {
                        "bbbs": bbbs,
                        "title": title,
                        "office": row.get("zdjgName"),
                        "publish": row.get("gbrq"),
                        "effective": row.get("sxrq"),
                        "sxx": sxx,
                        "status": SXX_NAME.get(sxx, str(sxx)),
                        "type": type_name,
                        "flxz": row.get("flxz"),
                        "flfgCodeId": row.get("flfgCodeId"),
                        "source": f"{BASE}/index.html",
                        "chars": len(text),
                    }
                    header = (
                        f"标题：{title}\n"
                        f"制定机关：{rec['office']}\n"
                        f"公布日期：{rec['publish']}\n"
                        f"施行日期：{rec['effective']}\n"
                        f"效力：{rec['status']}\n"
                        f"类型：{type_name}\n"
                        f"来源：国家法律法规数据库 {BASE}\n"
                        f"{'=' * 40}\n\n"
                    )
                    (TEXT_DIR / f"{fname}.txt").write_text(header + text, encoding="utf-8")
                    manifest.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    manifest.flush()
                    done.add(bbbs)
                    saved += 1
                    print(f"  已保存 [{type_name}] {title} 字数={len(text)}", flush=True)
                    save_checkpoint(done)

    save_checkpoint(done)
    summary = {
        "source": BASE,
        "saved_this_run": saved,
        "skipped_already_done": skipped,
        "done_ids": len(done),
        "text_dir": str(TEXT_DIR),
        "file_dir": str(FILE_DIR),
        "manifest": str(META_PATH),
        "scope": "宪法+法律全量（有效/尚未施行）；行政法规与司法解释按百姓高频关键词过滤；不含地方性法规。",
    }
    (DATA_DIR / "crawl_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"完成：本轮新增 {saved} 份，跳过 {skipped} 份。目录 {DATA_DIR}", flush=True)


if __name__ == "__main__":
    main()
