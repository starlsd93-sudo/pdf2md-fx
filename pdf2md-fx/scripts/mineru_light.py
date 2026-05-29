#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MinerU Agent 轻量解析 API 客户端（B/C 类）。免 token，仅回传 markdown（无 images/json）。
限制：单文件 ≤10MB / ≤20 页（超限请先用 pdf_utils.py split --batch 20）。

流程：POST /api/v1/agent/parse/file 取签名URL -> PUT 上传 -> GET 轮询 -> 下载 markdown_url。

用法：
  python mineru_light.py FILE [FILE ...] --out DIR [--lang ch] [--ocr|--no-ocr] [--no-formula]
  --lang   ch(默认,中英) / en / latin(德法等拉丁) / east_slavic(俄乌等西里尔)
  --ocr / --no-ocr  强制开/关 OCR；缺省时按 --auto 自行探测(<50字符/页→OCR)
  --auto   未显式给 --ocr/--no-ocr 时，按 pypdf 字符数自动判定
公式默认开启(enable_formula=True)，C 类务必保留。
"""
import argparse, json, sys, time
from pathlib import Path
import requests

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
API = "https://mineru.net/api/v1/agent/parse"
HDR = {"Content-Type": "application/json"}


def auto_ocr(pdf):
    from pypdf import PdfReader
    r = PdfReader(str(pdf)); n = len(r.pages) or 1
    avg = sum(len(p.extract_text() or "") for p in r.pages) / n
    return avg < 50


def parse_one(pdf, language, is_ocr, enable_formula, poll=5, timeout=600):
    rec = {"name": pdf.stem, "language": language, "is_ocr": is_ocr,
           "state": None, "post_s": None, "parse_s": None, "md_chars": None, "err": None}
    t0 = time.time()
    body = {"file_name": pdf.name, "language": language, "is_ocr": is_ocr,
            "enable_formula": enable_formula, "enable_table": True}
    r = requests.post(f"{API}/file", headers=HDR, json=body, timeout=60); r.raise_for_status()
    d = r.json()
    if d.get("code") != 0:
        rec["err"] = f"POST {d.get('code')} {d.get('msg')}"; return rec, None
    task_id, file_url = d["data"]["task_id"], d["data"]["file_url"]
    with open(pdf, "rb") as fh:
        requests.put(file_url, data=fh, timeout=600).raise_for_status()
    rec["post_s"] = round(time.time() - t0, 2)
    tp = time.time(); md_url = None; deadline = time.time() + timeout; last = None
    while time.time() < deadline:
        gd = requests.get(f"{API}/{task_id}", headers=HDR, timeout=60).json()["data"]
        st = gd.get("state")
        if st != last:
            print(f"   [{pdf.stem[:34]}] {st}"); last = st
        if st == "done":
            md_url = gd.get("markdown_url"); rec["state"] = "done"; break
        if st == "failed":
            rec["state"] = "failed"; rec["err"] = f"{gd.get('err_code')} {gd.get('err_msg')}"; break
        time.sleep(poll)
    rec["parse_s"] = round(time.time() - tp, 2)
    if not md_url:
        rec["state"] = rec["state"] or "timeout"; return rec, None
    md = requests.get(md_url, timeout=120).content.decode("utf-8", "replace")
    rec["md_chars"] = len(md)
    return rec, md


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--lang", default="ch")
    ap.add_argument("--ocr", dest="ocr", action="store_true", default=None)
    ap.add_argument("--no-ocr", dest="ocr", action="store_false")
    ap.add_argument("--no-formula", action="store_true")
    ap.add_argument("--poll", type=int, default=5)
    args = ap.parse_args()
    out_dir = Path(args.out); out_dir.mkdir(parents=True, exist_ok=True)
    runlog = []
    for f in args.files:
        pdf = Path(f)
        is_ocr = auto_ocr(pdf) if args.ocr is None else args.ocr
        print(f"\n>>> {pdf.name}  lang={args.lang} is_ocr={is_ocr} formula={not args.no_formula}")
        try:
            rec, md = parse_one(pdf, args.lang, is_ocr, not args.no_formula, poll=args.poll)
        except Exception as e:
            rec, md = {"name": pdf.stem, "state": "exception", "err": str(e)}, None
        if md is not None:
            (out_dir / f"{pdf.stem}.md").write_text(md, encoding="utf-8")
            print(f"   OK {rec['state']} parse={rec.get('parse_s')}s md_chars={rec.get('md_chars')} -> {pdf.stem}.md")
        else:
            print(f"   FAIL {rec.get('state')} {rec.get('err')}")
        runlog.append(rec); time.sleep(3)
    (out_dir / "_light_runlog.json").write_text(json.dumps(runlog, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n日志 -> {out_dir/'_light_runlog.json'}")


if __name__ == "__main__":
    main()
