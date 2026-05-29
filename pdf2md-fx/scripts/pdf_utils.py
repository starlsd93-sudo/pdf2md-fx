#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pdf2md-fx 公共工具：探测(probe) + 分批(split)。最省 token 的本地预处理。

子命令：
  probe  PDF [PDF ...]            判定页数 + 文字/图片型（pypdf 字符数，0 Claude token）
  split  PDF --batch N --tmp DIR  按 N 页分批，存入临时目录，输出分卷清单

probe 判据：平均每页文字层字符数 < 50 → 图片型(需 OCR)，否则文字型。
split 用于：A 类 >200 页按 193 页(留 7 页裕度)；B/C 类按 20 页(轻量 API 上限)。
分卷命名：<stem>__part01.pdf, __part02.pdf ...（零填充，保证字典序=页序）。

输出统一为 JSON（stdout 最后一行 RESULT=<json>），便于调用方解析。
"""
import argparse, json, sys
from pathlib import Path
from pypdf import PdfReader, PdfWriter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
IMG_THRESHOLD = 50


def probe_one(pdf: Path, sample_pages=None):
    reader = PdfReader(str(pdf))
    pages = len(reader.pages)
    idxs = range(pages) if not sample_pages else range(min(pages, sample_pages))
    total = sum(len(reader.pages[i].extract_text() or "") for i in idxs)
    n = len(list(idxs)) or 1
    avg = total / n
    ftype = "image" if avg < IMG_THRESHOLD else "text"
    return {"path": str(pdf), "name": pdf.stem, "pages": pages,
            "avg_chars_per_page": round(avg, 1), "type": ftype, "is_ocr": ftype == "image"}


def split_one(pdf: Path, batch: int, tmp: Path):
    reader = PdfReader(str(pdf))
    pages = len(reader.pages)
    tmp.mkdir(parents=True, exist_ok=True)
    parts = []
    if pages <= batch:
        return {"path": str(pdf), "pages": pages, "batched": False, "parts": [str(pdf)]}
    nparts = (pages + batch - 1) // batch
    width = max(2, len(str(nparts)))
    for k in range(nparts):
        w = PdfWriter()
        lo, hi = k * batch, min((k + 1) * batch, pages)
        for i in range(lo, hi):
            w.add_page(reader.pages[i])
        out = tmp / f"{pdf.stem}__part{str(k+1).zfill(width)}.pdf"
        with open(out, "wb") as fh:
            w.write(fh)
        parts.append({"part": k + 1, "path": str(out), "page_lo": lo + 1, "page_hi": hi})
    return {"path": str(pdf), "pages": pages, "batched": True, "batch": batch, "parts": parts}


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("probe"); p.add_argument("files", nargs="+")
    p.add_argument("--sample", type=int, default=None, help="只抽前 N 页判类型(加速大文件)")
    s = sub.add_parser("split"); s.add_argument("file")
    s.add_argument("--batch", type=int, required=True)
    s.add_argument("--tmp", required=True)
    args = ap.parse_args()

    if args.cmd == "probe":
        rows = [probe_one(Path(f), args.sample) for f in args.files]
        for r in rows:
            print(f"{r['type']:5s} ocr={str(r['is_ocr']):5s} pages={r['pages']:4d} avg={r['avg_chars_per_page']:8.1f}  {r['name']}")
        print("RESULT=" + json.dumps(rows, ensure_ascii=False))
    else:
        res = split_one(Path(args.file), args.batch, Path(args.tmp))
        if res["batched"]:
            print(f"{Path(args.file).name}: {res['pages']} 页 -> {len(res['parts'])} 批 (每批 {args.batch})")
            for pt in res["parts"]:
                print(f"  part{pt['part']}: 页 {pt['page_lo']}-{pt['page_hi']}  {Path(pt['path']).name}")
        else:
            print(f"{Path(args.file).name}: {res['pages']} 页 <= {args.batch}，无需分批")
        print("RESULT=" + json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main()
