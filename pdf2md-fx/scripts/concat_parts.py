#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
C 类/B 图片型解析收尾「归位」：把过程目录(_mineru_out)里的解析结果整理到源目录。

布局约定（v1.0.2）：
  - 最终 md 一律落「源目录」（PDF 旁）：
      · 分批文献 -> 合并各 <stem>__partNN.md 为 <stem>.md，写入源目录（part md 留在过程目录）
      · 未分批文献 -> 单篇 <stem>.md 直接「移动」到源目录（过程目录不再保留）
  - 过程目录(_mineru_out)只留分批的 part md（中间产物）。

用法：
  python concat_parts.py --proc <过程目录> --dest <源目录> [--all | --stem "<原PDF名>"]
    --all          扫描过程目录，自动归位全部文献（分批合并 + 单篇移动）
    --stem NAME    只处理指定文献
合并时批间插入 <!-- ===== PART BOUNDARY ===== -->。用 iterdir+正则匹配，
兼容文件名含 []()、空格、连字符等。
"""
import argparse, re, shutil, sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
PART_RE = re.compile(r"^(.*)__part(\d+)\.md$", re.I)


def merge_parts(parts, dest_md):
    parts.sort(key=lambda p: int(PART_RE.match(p.name).group(2)))
    chunks = []
    for k, p in enumerate(parts):
        if k > 0:
            chunks.append("\n\n<!-- ===== PART BOUNDARY ===== -->\n\n")
        chunks.append(p.read_text(encoding="utf-8", errors="replace"))
    merged = "".join(chunks)
    dest_md.write_text(merged, encoding="utf-8")
    return len(parts), len(merged)


def part_groups(proc):
    groups = {}
    for p in proc.iterdir():
        if p.is_file() and p.suffix.lower() == ".md":
            m = PART_RE.match(p.name)
            if m:
                groups.setdefault(m.group(1), []).append(p)
    return groups


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--proc", required=True, help="过程目录(_mineru_out 下解析输出)")
    ap.add_argument("--dest", required=True, help="源目录(PDF 旁，最终 md 落点)")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--stem", default=None)
    args = ap.parse_args()
    proc = Path(args.proc); dest = Path(args.dest); dest.mkdir(parents=True, exist_ok=True)
    groups = part_groups(proc)

    if args.stem and not args.all:
        parts = groups.get(args.stem, [])
        if parts:
            n, c = merge_parts(parts, dest / f"{args.stem}.md")
            print(f"[合并] {args.stem}: {n} 批 -> {dest}\\{args.stem}.md ({c} 字符)")
        else:
            src = proc / f"{args.stem}.md"
            if src.exists():
                shutil.move(str(src), str(dest / f"{args.stem}.md"))
                print(f"[归位] {args.stem} -> {dest}\\{args.stem}.md")
            else:
                sys.exit(f"未找到 {args.stem} 的分卷或单篇 md @ {proc}")
        return

    # --all：先合并分批组，再移动单篇
    merged_stems = set()
    for stem, parts in groups.items():
        n, c = merge_parts(parts, dest / f"{stem}.md")
        merged_stems.add(stem)
        print(f"[合并] {stem}: {n} 批 -> 源目录\\{stem}.md ({c} 字符)")
    for p in list(proc.iterdir()):
        if not (p.is_file() and p.suffix.lower() == ".md"):
            continue
        if PART_RE.match(p.name):
            continue                      # part md 留在过程目录
        stem = p.stem
        if stem in merged_stems:
            p.unlink()                    # 过程目录里的旧合并产物，清掉（合并版已落源目录）
            continue
        shutil.move(str(p), str(dest / p.name))
        print(f"[归位] {stem} -> 源目录\\{p.name}")
    print(f"完成：合并 {len(merged_stems)} 篇，单篇归位若干；part md 保留在 {proc}")


if __name__ == "__main__":
    main()
