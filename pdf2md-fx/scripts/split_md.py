#!/usr/bin/env python3
"""
split_md.py — 将超过 Typora 大小限制的合并 MD 按 BATCH BOUNDARY 拆分

使用场景：merge_md.py 合并后若 merged.md > MAX_SIZE (默认 1.5 MB)，
自动或手动调用本脚本，在原有批次边界处拆分为多个独立 MD 文件。

用法：
  python split_md.py --md "<merged.md>" --out "<目标目录>" --title "<文献名>"
  python split_md.py --md "<merged.md>" --out "<目标目录>" --title "<文献名>" --max-size 1.5
  python split_md.py --md "<merged.md>" --out "<目标目录>" --title "<文献名>" --check-only

说明：
  - 所有拆分文件共享同一个 img-<title>/ 文件夹（相对路径不变，不需复制图片）
  - BATCH BOUNDARY HTML 注释行被移除（保持 MD 整洁）
  - 输出文件名：<title>_Part01.md, <title>_Part02.md ...
  - --check-only：仅检测是否需要拆分，输出 JSON 状态，exit 0=无需 1=需要
"""

import re
import sys
import json
import argparse
from pathlib import Path

# Typora 默认大小限制（字节），超过此值建议拆分
TYPORA_DEFAULT_LIMIT = 2_000_000   # 2 MB
RECOMMENDED_SPLIT_SIZE = 1_500_000  # 1.5 MB (留裕度)

BOUNDARY_RE = re.compile(
    r'<!--\s*={3,}\s*BATCH BOUNDARY\s+(.+?)\s*={3,}\s*-->'
)


def find_boundaries(lines: list[str]) -> list[int]:
    """返回所有 BATCH BOUNDARY 注释所在的行索引（0-based）。"""
    idxs = []
    for i, line in enumerate(lines):
        if BOUNDARY_RE.search(line):
            idxs.append(i)
    return idxs


def split_at_boundaries(lines: list[str], boundary_idxs: list[int]) -> list[list[str]]:
    """将 lines 按 boundary_idxs 切分为多段（每段不含 BOUNDARY 行本身）。"""
    segments = []
    starts = [0] + [idx + 1 for idx in boundary_idxs]
    ends   = boundary_idxs + [len(lines)]

    for s, e in zip(starts, ends):
        seg = lines[s:e]
        # 去掉段首/段尾的纯空行（最多 3 行）
        while seg and seg[0].strip() == '':
            seg.pop(0)
        while seg and seg[-1].strip() == '':
            seg.pop()
        segments.append(seg)

    return segments


def size_of(lines: list[str]) -> int:
    return sum(len(l) + 1 for l in lines)


def main():
    ap = argparse.ArgumentParser(description='按 BATCH BOUNDARY 拆分超大合并 MD')
    ap.add_argument('--md',         required=True, help='合并后的 merged.md 路径')
    ap.add_argument('--out',        required=True, help='输出目录（拆分文件落此处）')
    ap.add_argument('--title',      required=True, help='文献名（输出文件名前缀）')
    ap.add_argument('--max-size',   type=float, default=1.5,
                    help='触发拆分的阈值 MB（默认 1.5）')
    ap.add_argument('--check-only', action='store_true',
                    help='仅检查是否需要拆分，exit 1=需要，exit 0=无需')
    args = ap.parse_args()

    md_path  = Path(args.md)
    out_dir  = Path(args.out)
    title    = args.title
    max_bytes = int(args.max_size * 1_000_000)

    if not md_path.exists():
        print(f'[ERROR] MD 文件不存在: {md_path}', file=sys.stderr)
        sys.exit(2)

    md_size = md_path.stat().st_size
    md_size_mb = md_size / 1_000_000

    # --check-only 模式
    if args.check_only:
        need_split = md_size > max_bytes
        result = {
            'md_size_bytes': md_size,
            'md_size_mb': round(md_size_mb, 2),
            'threshold_mb': args.max_size,
            'need_split': need_split
        }
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(1 if need_split else 0)

    print(f'MD 大小: {md_size_mb:.2f} MB  阈值: {args.max_size} MB')

    if md_size <= max_bytes:
        print(f'[OK] 文件未超阈值，无需拆分。')
        sys.exit(0)

    # 读取内容
    content = md_path.read_text(encoding='utf-8')
    lines   = content.split('\n')

    boundary_idxs = find_boundaries(lines)
    if not boundary_idxs:
        print('[WARN] 未找到 BATCH BOUNDARY 标记，无法按批次拆分。')
        print('       请检查 merged.md 是否由 merge_md.py 生成。')
        sys.exit(3)

    print(f'找到 {len(boundary_idxs)} 处批次边界 → 拆分为 {len(boundary_idxs)+1} 个文件')

    segments = split_at_boundaries(lines, boundary_idxs)
    out_dir.mkdir(parents=True, exist_ok=True)

    n_parts = len(segments)
    pad = len(str(n_parts))  # 位数补零

    print(f'\n{"─"*60}')
    print(f'  {"文件名":<50}  {"大小 KB":>8}  {"行数":>6}')
    print(f'{"─"*60}')

    written = []
    for i, seg in enumerate(segments, 1):
        part_name = f'{title}_Part{str(i).zfill(pad)}.md'
        out_path  = out_dir / part_name

        seg_text = '\n'.join(seg)
        out_path.write_text(seg_text, encoding='utf-8')

        seg_kb   = round(out_path.stat().st_size / 1024, 1)
        seg_lines = len(seg)
        status = '[OK]' if out_path.stat().st_size < TYPORA_DEFAULT_LIMIT else '[WARN] >2MB'
        print(f'  {part_name:<50}  {seg_kb:>7.1f}  {seg_lines:>6}  {status}')
        written.append(str(out_path))

    print(f'{"─"*60}')
    print(f'\n拆分完成：{n_parts} 个文件 → {out_dir}')
    print(f'共享图片目录：img-{title}/ （与 MD 文件同级，路径无需修改）')
    result = {
        'n_parts': n_parts,
        'parts': written,
        'shared_img_folder': f'img-{title}'
    }
    print(f'\nRESULT={json.dumps(result, ensure_ascii=False)}')


if __name__ == '__main__':
    main()
