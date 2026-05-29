#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图片本地化（A 类·复制自 mineru-img-convert 的 mineru_convert.py，改为接受任意 md/images）。

功能：① 把 md 里 images/<hash> 引用改为相对路径 <img-folder>/<name>；
     ② 丢弃 md 未实际引用的图片（公式/表格临时图，约占 60-80%，不复制）；
     ③ 按图号/表号语义重命名被引用的图片（图1-1(a).jpg、表3-1_R1C2.jpg），
        无法定位的封面/logo 保留 hash 名。

与原版差异：不再要求 <title>.pdf-<UUID> 文件夹结构，改为显式参数：
  python img_localize.py --md MERGED.md --images IMG_DIR --out OUT_DIR --title 名称 [apply]
（A 类对 merge_md.py 产出的 merged.md + images/ 运行本脚本）
不传 apply = dry run。
"""
import re, sys, shutil, argparse
from pathlib import Path
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ap = argparse.ArgumentParser()
ap.add_argument("--md", required=True)
ap.add_argument("--images", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--title", required=True)
ap.add_argument("mode", nargs="?", default="dry")
args = ap.parse_args()

SRC_MD = Path(args.md); SRC_IMG = Path(args.images)
OUTPUT_DIR = Path(args.out); THESIS_TITLE = args.title
MODE = "apply" if args.mode == "apply" else "dry"
if not SRC_MD.exists():
    sys.exit(f"[ERR] md 不存在：{SRC_MD}")
if not SRC_IMG.exists():
    sys.exit(f"[ERR] images 不存在：{SRC_IMG}")


def truncate_title(title, max_zh=8, max_en=6):
    zh = sum(1 for c in title if '一' <= c <= '鿿')
    if zh >= 4:
        cnt, out = 0, []
        for ch in title:
            out.append(ch)
            if '一' <= ch <= '鿿':
                cnt += 1
                if cnt >= max_zh:
                    break
        return ''.join(out).rstrip()
    return ' '.join(title.split()[:max_en])


IMG_FOLDER_NAME = f"img-{truncate_title(THESIS_TITLE)}"
OUT_MD = OUTPUT_DIR / f"{THESIS_TITLE}.md"
OUT_IMG = OUTPUT_DIR / IMG_FOLDER_NAME

raw = SRC_MD.read_text(encoding="utf-8")
lines = raw.splitlines(keepends=True)

# hash 命名兼容：MinerU 图片名既可能是 60+ hex，也可能是其它；这里宽松匹配常见图片扩展
IMG_RE      = re.compile(r'!\[[^\]]*\]\(images/([^)]+\.(?:jpg|jpeg|png))\)')
HTML_IMG_RE = re.compile(r'<img[^>]+src="images/([^"]+\.(?:jpg|jpeg|png))"[^>]*/?>')
ANY_REF_RE  = re.compile(r'images/([A-Za-z0-9_\-]+\.(?:jpg|jpeg|png))')
SUB_CAP_RE  = re.compile(r'^\s*\(([a-zA-Z])\)\s')
MAIN_CAP_RE = re.compile(r'^\s*图\s*((?:[A-Za-z]|\d+)\s*[-–—]\s*\d+)')
SEC_RE      = re.compile(r'^#{1,6}\s*\d')


def norm_fig(s): return re.sub(r'\s*[-–—]\s*', '-', s).strip()


def fix_ocr_concat(captured, stripped, end):
    if end >= len(stripped):
        return captured
    im = stripped[end]
    if im.isascii() and im.isalpha():
        parts = re.split(r'[-]', captured, maxsplit=1)
        if len(parts) == 2 and len(parts[1].strip()) > 1:
            return parts[0] + '-' + parts[1].strip()[:-1]
    return captured


events = []
for i, line in enumerate(lines):
    stripped = line.strip()
    m = IMG_RE.search(line)
    if m:
        events.append(('img', i, m.group(1))); continue
    m = SUB_CAP_RE.match(line)
    if m:
        events.append(('sub', i, m.group(1).lower())); continue
    m = MAIN_CAP_RE.match(stripped)
    if m:
        fig = fix_ocr_concat(norm_fig(m.group(1)), stripped, m.end())
        if '续' in stripped:
            fig += '_续'
        events.append(('cap', i, fig)); continue
    if SEC_RE.match(stripped):
        events.append(('sec', i, stripped[:60]))

mapping = {}; warnings = []; accumulator = []; assigned_groups = []


def flush_block(fig_name):
    global accumulator, assigned_groups
    if accumulator:
        assigned_groups.append((None, list(accumulator))); accumulator.clear()
    merged_order = []; merged = defaultdict(list)
    for sub, imgs in assigned_groups:
        if sub not in merged:
            merged_order.append(sub)
        merged[sub].extend(imgs)
    if merged_order == [None]:
        imgs = merged[None]
        if len(imgs) == 1:
            mapping[imgs[0][1]] = f"{fig_name}.jpg"
        else:
            for k, (li, h) in enumerate(imgs):
                mapping[h] = f"{fig_name}_{k+1}.jpg"
    else:
        for sub in merged_order:
            imgs = merged[sub]
            if sub is None:
                for k, (li, h) in enumerate(imgs):
                    mapping[h] = f"{fig_name}_extra{k+1}.jpg"
                    warnings.append(f"[WARN] L{li+1}: {h[:16]} no sub-cap")
            elif len(imgs) == 1:
                mapping[imgs[0][1]] = f"{fig_name}({sub}).jpg"
            else:
                for k, (li, h) in enumerate(imgs):
                    mapping[h] = f"{fig_name}({sub})_{k+1}.jpg"
    assigned_groups.clear()


def discard_pending(reason):
    global accumulator, assigned_groups
    for sub, imgs in assigned_groups:
        for (li, h) in imgs:
            warnings.append(f"[SKIP] L{li+1}: {h[:16]} {reason}"); mapping[h] = None
    for (li, h) in accumulator:
        warnings.append(f"[SKIP] L{li+1}: {h[:16]} {reason}"); mapping[h] = None
    accumulator.clear(); assigned_groups.clear()


for ev in events:
    k = ev[0]
    if k == 'img':
        accumulator.append((ev[1], ev[2]))
    elif k == 'sub':
        if accumulator:
            assigned_groups.append((ev[2], list(accumulator))); accumulator.clear()
    elif k == 'cap':
        if accumulator or assigned_groups:
            flush_block(f"图{ev[2]}")
    elif k == 'sec':
        if accumulator or assigned_groups:
            discard_pending(f"sec:{ev[2][:30]}")
if accumulator or assigned_groups:
    discard_pending("eof")

all_ref = set()
for line in lines:
    for h in IMG_RE.findall(line):
        all_ref.add(h)
    for h in HTML_IMG_RE.findall(line):
        all_ref.add(h)
    for h in ANY_REF_RE.findall(line):
        all_ref.add(h)

# 表格单元格图：表X-Y_R<row>C<col>
TAB_CAP_RE = re.compile(r'^\s*表\s*((?:[A-Za-z]|\d+)\s*[-–—]\s*\d+)')
TR_RE = re.compile(r'<tr[^>]*>(.*?)</tr>', re.I | re.S)
TD_RE = re.compile(r'<t[dh][^>]*>(.*?)</t[dh]>', re.I | re.S)
INLINE_IMG = re.compile(r'<img[^>]+src="images/([^"]+\.(?:jpg|jpeg|png))"', re.I)
table_caps = []
for i, line in enumerate(lines):
    m = TAB_CAP_RE.match(line.strip())
    if m:
        num = re.sub(r'\s*[-–—]\s*', '-', m.group(1)).strip()
        if '续' in line:
            num += '_续'
        table_caps.append((i, num))
for i, line in enumerate(lines):
    if '<table' not in line or '<img' not in line:
        continue
    cap = next((n for ci, n in reversed(table_caps) if ci < i), None)
    if not cap:
        continue
    for r_idx, row in enumerate(TR_RE.findall(line)):
        for c_idx, cell in enumerate(TD_RE.findall(row)):
            for k, im in enumerate(INLINE_IMG.findall(cell)):
                suf = f"_{k+1}" if k > 0 else ""
                if mapping.get(im) is None or mapping.get(im) == im:
                    mapping[im] = f"表{cap}_R{r_idx}C{c_idx+1}{suf}.jpg"

unmapped = all_ref - set(h for h, n in mapping.items() if n)
for h in unmapped:
    if mapping.get(h) is None:
        mapping[h] = h  # 保留 hash 名

total_imgs = len(list(SRC_IMG.glob("*.jpg")) + list(SRC_IMG.glob("*.png")) + list(SRC_IMG.glob("*.jpeg")))
print("=" * 60)
print(f"  Title: {THESIS_TITLE}   Folder: {IMG_FOLDER_NAME}   Mode: {MODE.upper()}")
print(f"  TOTAL imgs: {total_imgs}   REFERENCED: {len(all_ref)}   UNREF(drop): {total_imgs-len(all_ref)}")
print(f"  warnings: {len(warnings)}")
shown = 0
for h, n in mapping.items():
    if n and n != h:
        print(f"  {h[:16]} -> {n}"); shown += 1
        if shown >= 8:
            break

if MODE == "apply":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if OUT_IMG.exists():
        for f in OUT_IMG.iterdir():
            if f.is_file():
                f.unlink()
    OUT_IMG.mkdir(parents=True, exist_ok=True)
    new_md = raw
    for h, name in mapping.items():
        if name:
            new_md = new_md.replace(f"images/{h}", f"{IMG_FOLDER_NAME}/{name}")
    OUT_MD.write_text(new_md, encoding="utf-8", newline="")
    copied = 0
    for h, name in mapping.items():
        if not name:
            continue
        src = SRC_IMG / h
        if src.exists():
            shutil.copy2(src, OUT_IMG / name); copied += 1
    remaining = len(re.findall(r'images/[A-Za-z0-9_\-]+\.(?:jpg|jpeg|png)', new_md))
    print(f"  MD saved: {OUT_MD.name}   Images copied: {copied}   Remaining 'images/' refs: {remaining}")
    print("DONE" if remaining == 0 else "[WARN] 仍有未改写引用")
