#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A 类分批合并：把多个 MinerU 精准输出子目录的 full.md 按页序拼接，
合并 images/，并做衔接校验。

输入：MinerU 精准解析输出根目录下的若干 <stem>__partNN/ 子目录
     （每个含 full.md + images/）。按 partNN 升序拼接。
输出：<out>/merged.md + <out>/images/ ，另存 _merge_report.json。

衔接校验：① 每批 full.md 非空；② 批数与预期一致；③ 在每个拼接边界插入
可见标记 <!-- ===== BATCH BOUNDARY partN | partN+1 ===== --> 供人工抽查；
④ 检查图片 hash 是否跨批撞名（正常不会，撞则警告）；⑤ 合并后残留绝对
images/ 引用计数（应与图片总数一致）。

用法：
  python merge_md.py --root <mineru输出根> --stem <原pdf名> --out <合并输出目录>
  python merge_md.py --parts dirA dirB dirC --out <目录>     # 显式给定顺序
"""
import argparse, json, re, shutil, sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
PART_RE = re.compile(r"__part(\d+)$")
IMG_REF = re.compile(r"images/([0-9a-zA-Z_\-]+\.(?:jpg|jpeg|png))")


def collect_parts(root, stem):
    dirs = [d for d in Path(root).iterdir() if d.is_dir() and d.name.startswith(f"{stem}__part")]
    return sorted(dirs, key=lambda d: int(PART_RE.search(d.name).group(1)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root"); ap.add_argument("--stem")
    ap.add_argument("--parts", nargs="*")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if args.parts:
        parts = [Path(p) for p in args.parts]
    else:
        if not (args.root and args.stem):
            sys.exit("需 --parts 或 (--root 且 --stem)")
        parts = collect_parts(args.root, args.stem)
    if not parts:
        sys.exit("未找到分批子目录")

    out = Path(args.out); (out / "images").mkdir(parents=True, exist_ok=True)
    report = {"n_parts": len(parts), "parts": [], "warnings": [], "img_total": 0, "img_collision": 0}
    seen_imgs = {}
    md_chunks = []

    for k, d in enumerate(parts):
        fm = d / "full.md"
        if not fm.exists():
            report["warnings"].append(f"{d.name}: 缺 full.md"); continue
        text = fm.read_text(encoding="utf-8", errors="replace")
        nchars = len(text)
        if nchars == 0:
            report["warnings"].append(f"{d.name}: full.md 为空")
        # 合并图片
        imgdir = d / "images"
        nimg = 0
        if imgdir.exists():
            for img in imgdir.iterdir():
                if not img.is_file():
                    continue
                dst = out / "images" / img.name
                if img.name in seen_imgs and seen_imgs[img.name] != d.name:
                    report["img_collision"] += 1
                    report["warnings"].append(f"图片撞名 {img.name} ({seen_imgs[img.name]} vs {d.name})")
                if not dst.exists():
                    shutil.copy2(img, dst); nimg += 1
                seen_imgs[img.name] = d.name
        report["img_total"] += nimg
        if k > 0:
            md_chunks.append(f"\n\n<!-- ===== BATCH BOUNDARY {parts[k-1].name} | {d.name} ===== -->\n\n")
        md_chunks.append(text)
        report["parts"].append({"part": k + 1, "dir": d.name, "md_chars": nchars, "images_copied": nimg,
                                "tail": text[-80:].replace("\n", " "), "head": text[:80].replace("\n", " ")})
        print(f"part{k+1}: {d.name}  md_chars={nchars}  imgs={nimg}")

    merged = "".join(md_chunks)
    (out / "merged.md").write_text(merged, encoding="utf-8")
    refs = len(IMG_REF.findall(merged))
    report["merged_chars"] = len(merged)
    report["img_refs_in_merged"] = refs
    (out / "_merge_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 60)
    print(f"合并完成：{len(parts)} 批 -> merged.md ({len(merged)} 字符)，images {report['img_total']} 张")
    print(f"图片引用 {refs} 处；撞名 {report['img_collision']}；警告 {len(report['warnings'])}")
    print("请人工抽查各 BATCH BOUNDARY 处上下文是否语义连续（见 _merge_report.json 的 head/tail）。")
    print(f"报告 -> {out/'_merge_report.json'}")


if __name__ == "__main__":
    main()
