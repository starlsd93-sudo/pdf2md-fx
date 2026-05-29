#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地原生读取（B 类·文字型）：字符级分栏判断与合并，0 Claude token、亚秒级。
仅适用于「文字型且不含公式」的 PDF —— 公式会结构性崩溃（用 MinerU 走 C 类）。

分栏算法：pdfminer 取字符级 bbox；按 x 中心直方图在中部找栏间空白带
（中部最稀 bin < 全页中位数 55% → 双栏）；双栏页每个视觉行从切分点切左右半，
左栏整体在前、右栏在后；单栏页行内按 x 顺序。

用法：
  python local_read.py INPUT.pdf [--out OUT.md] [--max-chars N]
--max-chars：超过则在该字符数处截断并提示（配合模型上下文上限，见 SKILL.md 决策）。
"""
import argparse, statistics, sys
from pathlib import Path
from pypdf import PdfReader
from pdfminer.high_level import extract_pages
from pdfminer.layout import LTChar, LAParams

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def get_chars(page_layout):
    out = []
    def rec(o):
        if isinstance(o, LTChar):
            x0, y0, x1, y1 = o.bbox
            out.append([(x0 + x1) / 2, (y0 + y1) / 2, x0, x1, y1 - y0, o.get_text()])
        elif hasattr(o, "__iter__"):
            for c in o:
                rec(c)
    rec(page_layout)
    return out


def cluster_rows(chars, hmed):
    chars = sorted(chars, key=lambda c: -c[1])
    rows, cur, cy = [], [], None
    for c in chars:
        if cy is None or abs(c[1] - cy) <= 0.5 * hmed:
            cur.append(c); cy = c[1] if cy is None else (cy + c[1]) / 2
        else:
            rows.append(cur); cur, cy = [c], c[1]
    if cur:
        rows.append(cur)
    return rows


def row_text(cells, wmed):
    cells = sorted(cells, key=lambda c: c[2])
    s, prev_x1 = "", None
    for cx, ym, x0, x1, h, ch in cells:
        if prev_x1 is not None and x0 - prev_x1 > 0.3 * wmed:
            s += " "
        s += ch; prev_x1 = x1
    return s.rstrip()


def detect_split(chars, page_w, nbins=40):
    hist = [0] * nbins
    bw = page_w / nbins
    for c in chars:
        b = min(nbins - 1, max(0, int(c[0] / bw)))
        hist[b] += 1
    nz = [x for x in hist if x > 0]
    if not nz:
        return None
    med = statistics.median(nz)
    lo, hi = int(0.30 * nbins), int(0.70 * nbins)
    j = min(range(lo, hi), key=lambda i: hist[i])
    return (j + 0.5) * bw if hist[j] < 0.55 * med else None


def order_page(chars, page_w):
    if not chars:
        return False, ""
    hmed = statistics.median([c[4] for c in chars]) or 10
    wmed = statistics.median([c[3] - c[2] for c in chars]) or 5
    split = detect_split(chars, page_w)
    rows = cluster_rows(chars, hmed)
    if split is None:
        return False, "\n".join(row_text(r, wmed) for r in rows if r)
    mid = split
    left_lines, right_lines = [], []
    for r in rows:
        L = [c for c in r if c[0] < mid]
        R = [c for c in r if c[0] >= mid]
        if L:
            left_lines.append(row_text(L, wmed))
        if R:
            right_lines.append(row_text(R, wmed))
    body = [l for l in left_lines if l.strip()] + [l for l in right_lines if l.strip()]
    return True, "\n".join(body)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--out", default=None)
    ap.add_argument("--max-chars", type=int, default=None)
    args = ap.parse_args()
    pdf = Path(args.pdf)
    out = Path(args.out) if args.out else pdf.with_suffix(".md")

    parts, flags = [], []
    for pl in extract_pages(str(pdf), laparams=LAParams()):
        two, text = order_page(get_chars(pl), pl.width)
        flags.append("2" if two else "1")
        parts.append(text)
    md = "\n\n".join(parts)
    truncated = False
    if args.max_chars and len(md) > args.max_chars:
        md = md[:args.max_chars] + "\n\n<!-- [truncated at max-chars] -->"
        truncated = True
    out.write_text(md, encoding="utf-8")
    print(f"cols=[{''.join(flags)}]  chars={len(md)}  truncated={truncated}  -> {out}")


if __name__ == "__main__":
    main()
