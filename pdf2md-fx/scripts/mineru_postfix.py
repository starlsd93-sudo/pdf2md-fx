#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MinerU 精准 API 产出 MD 的后处理修正（A 类·v1.3 算法重写）。

前提：MinerU 不会漏掉标题，正文每个标题都已被标为 #（多为同一级 h1），
缺的只是「正确的层级」与「序号」。本脚本据此分四步修订：

  步骤 1  目录区误标题 → 还原正文
          以「目录」标题为起点、其后第一个「干净标题」（无点引线页码尾，
          通常是『图清单』或正文首个『第X章』）为终点，区间内所有 # 行
          都是目录条目 → 去掉 # 还原为正文。另对全文任何带「点引线+页码」
          尾巴的 # 行（如『图 1-1 …. 3』残留清单条目）一并还原。

  步骤 2  正文标题按行首序号定级（『字母注释表』之后为正文主体，但本步
          对目录区以外的所有标题统一生效，前置/附录同理）：
            第X章          → #     (h1)
            X.X            → ##    (h2)
            X.X.X          → ###   (h3)
            X.X.X.X        → ####  (h4)   （按小数点段数定级，封顶 h6）
            (X) / （X）    → ##### (h5)   半/全角括号数字小标题
          删除每张图后 MinerU 注入的 <details><summary>类型</summary>…</details>
          图片描述块（text_image / natural_image / flowchart 等约 17 种 AI 图注）。

  步骤 3  无序号标题 → 回填目录序号再定级
          先解析目录区，建立『标题文字 → 序号』映射；正文中无序号的标题
          若能在目录里找到同名条目且该条目带序号，则把序号补进标题并按
          序号定级（如 `# 研究背景` + 目录『1.1 研究背景』→ `## 1.1 研究背景`）。

  步骤 4  目录里也没有序号 → 保持原样（级别不动），留待人工处理。

用法：
  python mineru_postfix.py --md FILE.md [--out OUT.md] [apply]
    不传 apply           = dry run，只打印将改动的统计与样例，不写文件。
    传 apply 不带 --out  = 原地覆盖 FILE.md。
    传 apply 带 --out    = 写到 OUT.md（不动原文件）。
"""
import re, sys, argparse
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ap = argparse.ArgumentParser()
ap.add_argument("--md", required=True)
ap.add_argument("--out", default=None)
ap.add_argument("mode", nargs="?", default="dry")
args = ap.parse_args()

MD = Path(args.md)
if not MD.exists():
    sys.exit(f"[ERR] md 不存在：{MD}")
MODE = "apply" if args.mode == "apply" else "dry"
OUT = Path(args.out) if args.out else MD

raw = MD.read_text(encoding="utf-8")

# ── 图片描述 <details> 块删除（步骤 2 的一部分）─────────────────────────
# 仅匹配 summary 为单个小写蛇形标签（text_image / surface_3d / bar_line …），
# 即 MinerU 自动分类标签；人工撰写的 <details>（summary 含空格/大写）保留。
DETAILS_RE = re.compile(
    r'[ \t]*<details>\s*<summary>\s*([a-z][a-z0-9_]*)\s*</summary>.*?</details>[ \t]*\n?',
    re.S,
)
det_types = DETAILS_RE.findall(raw)
text = DETAILS_RE.sub("", raw)
text = re.sub(r'\n{3,}', '\n\n', text)

# ── 正则 ────────────────────────────────────────────────────────────────
HEAD_RE  = re.compile(r'^(#{1,6})[ \t]+(.*\S)[ \t]*$')                 # 标题行
SECNUM   = r'第\s*[一二三四五六七八九十百千零〇0-9]+\s*章|\d+(?:\.\d+)*'  # 序号通式
CHAP_RE  = re.compile(r'^第\s*[一二三四五六七八九十百千零〇0-9]+\s*章')   # 第X章
NUM_RE   = re.compile(r'^(\d+(?:\.\d+)+)')                             # X.X[.X…]（含点）
NUM1_RE  = re.compile(r'^(\d+)(?=[\s、，．.)）:：]|$)')                  # 独立数字章号
PAREN_RE = re.compile(r'^[(（]\s*(?:\d+|[一二三四五六七八九十]+)\s*[)）]') # (X)/（X）小标题
TOCNUM_RE = re.compile(r'^\s*(' + SECNUM + r')\s*(.*)$')              # 目录条目拆序号
# 引线符集合：英文句点 / 中文省略号 / 间隔号 / 全角句号 / 项目符 等
LEADER = r'.…·․‧•・．。'
PAGE_TAIL = re.compile(r'[\s' + LEADER + r']+[0-9ivxlcdmIVXLCDM]*\s*$')  # 引线+页码尾


def is_toc_entry(t):
    """带引线 / 尾页码 = 目录或图表清单条目（不应是标题）。
    兼容多种引线写法：「....」「. .」「……」「··」以及引线被 MinerU 丢失只剩
    「序号 + 空格 + 页码」（如『第三章 刚体动力学建模 43』）。"""
    t = t.strip()
    # (a) 2+ 连续引线符
    if re.search(r'[' + LEADER + r']{2,}', t):
        return True
    # (b) 单引线符(与空格相邻) + 行尾页码（阿拉伯或罗马）；要求空格以排除小数 7.4
    if re.search(r'(?:\s[' + LEADER + r']|[' + LEADER + r']\s)\s*[0-9ivxlcdmIVXLCDM]{1,5}\s*$', t):
        return True
    # (c) 序号(第X章 / X.X)开头 且 行尾为「空白 + 页码」（引线整段丢失）
    if re.match(r'^(?:第\s*[一二三四五六七八九十百千零〇0-9]+\s*章|\d+(?:\.\d+)*)', t) \
       and re.search(r'\s+\d{1,4}\s*$', t):
        return True
    # (d) 序号/章节词开头 且 仅以引线符结尾（页码被 MinerU 丢失，如「第一章 绪论.」）
    #     行尾无数字，排除标题内含小数的正文标题
    if re.search(r'[' + LEADER + r']\s*$', t) and not re.search(r'\d\s*$', t) \
       and re.match(r'^(?:第\s*\S+\s*[章节]|附录|参考文献|致\s*谢|后\s*记|\d)', t):
        return True
    return False


def norm(t):
    """标题归一化（去空格与轻量标点、英文转小写）用于目录↔正文比对。"""
    return re.sub(r'[\s.．。·・…,，、:：;；()（）]+', '', t).casefold()


def num_level(num_str):
    """序号 → 级别。第X章→1；按小数点段数定级，封顶 6。"""
    if '章' in num_str:
        return 1
    return min(len(num_str.split('.')), 6)


def clean_num(num_str):
    """规整序号文字（第 一 章→第一章）。"""
    return re.sub(r'\s+', '', num_str)


lines = text.split('\n')

# ── 定位关键锚点：目录标题 i_toc、目录区终点 toc_end ───────────────────
heads = []  # (idx, hashes, title)
for i, ln in enumerate(lines):
    m = HEAD_RE.match(ln)
    if m:
        heads.append((i, m.group(1), m.group(2).strip()))

i_toc = None
for idx, _, title in heads:
    if norm(title) == "目录" and not is_toc_entry(title):
        i_toc = idx
        break

toc_end = None
if i_toc is not None:
    for idx, _, title in heads:
        if idx > i_toc and not is_toc_entry(title):
            toc_end = idx          # 目录区后第一个干净标题（图清单 / 首个第X章）
            break
    if toc_end is None:
        toc_end = len(lines)

# ── 步骤 3 准备：解析目录区，建立 标题→序号 映射 ───────────────────────
toc_map = {}
if i_toc is not None:
    for i in range(i_toc + 1, toc_end):
        ln = lines[i]
        body = HEAD_RE.match(ln)
        ln = body.group(2) if body else ln          # 目录里若有 # 也剥掉
        m = TOCNUM_RE.match(ln)
        if not m:
            continue
        num = clean_num(m.group(1))
        core = PAGE_TAIL.sub('', m.group(2)).strip()  # 去掉点引线+页码
        if core:
            toc_map.setdefault(norm(core), num)

# ── 逐行处理 ────────────────────────────────────────────────────────────
out = []
n_toc = 0                       # 步骤1 还原条目数
n_paren = 0                     # 步骤2 (X)→h5 数
n_recover = 0                   # 步骤3 回填序号数
n_keep = 0                      # 步骤4 无序号保持原样数
lvl_cnt = Counter()
toc_s, paren_s, recover_s, keep_s = [], [], [], []

for i, ln in enumerate(lines):
    m = HEAD_RE.match(ln)
    if not m:
        out.append(ln)
        continue
    hashes, title = m.group(1), m.group(2).strip()

    # 步骤 1：目录区内 / 任何带点引线页码的标题 → 还原正文
    in_toc_region = (i_toc is not None and i_toc < i < toc_end)
    if in_toc_region or is_toc_entry(title):
        out.append(title)
        n_toc += 1
        if len(toc_s) < 6:
            toc_s.append(title[:50])
        continue

    # 步骤 2：(X)/（X） 小标题 → h5
    if PAREN_RE.match(title):
        out.append('#' * 5 + ' ' + title)
        lvl_cnt[5] += 1
        n_paren += 1
        if len(paren_s) < 6:
            paren_s.append(title[:40])
        continue

    # 步骤 2：第X章 → h1
    if CHAP_RE.match(title):
        out.append('# ' + title)
        lvl_cnt[1] += 1
        continue

    # 步骤 2：X.X[.X…] → 按段数定级
    mm = NUM_RE.match(title)
    if mm:
        lv = min(len(mm.group(1).split('.')), 6)
        out.append('#' * lv + ' ' + title)
        lvl_cnt[lv] += 1
        continue

    # 步骤 2：独立数字章号 → h1
    if NUM1_RE.match(title):
        out.append('# ' + title)
        lvl_cnt[1] += 1
        continue

    # 步骤 3：无序号 → 回填目录序号
    key = norm(title)
    if key in toc_map:
        num = toc_map[key]
        lv = num_level(num)
        out.append('#' * lv + ' ' + num + ' ' + title)
        lvl_cnt[lv] += 1
        n_recover += 1
        if len(recover_s) < 8:
            recover_s.append(f"{num} {title[:34]}")
        continue

    # 步骤 4：目录也无序号 → 保持原样（级别不动）
    out.append(hashes + ' ' + title)
    lvl_cnt[len(hashes)] += 1
    n_keep += 1
    if len(keep_s) < 8:
        keep_s.append(title[:40])

result = '\n'.join(out)

# ── 报告 ────────────────────────────────────────────────────────────────
print("=" * 66)
print(f"  MinerU 后处理修正 v1.3    Mode: {MODE.upper()}")
print(f"  文件：{MD.name}")
toc_desc = (f"目录『{lines[i_toc].lstrip('# ').strip()}』(行{i_toc + 1}) "
            f"→ 终点行{toc_end + 1 if toc_end and toc_end < len(lines) else 'EOF'}"
            if i_toc is not None else "未找到『目录』标题，跳过目录区还原")
print(f"  锚点：{toc_desc}")
print("-" * 66)
print(f"  步骤1 目录/清单条目 → 还原正文：{n_toc} 行")
for s in toc_s:
    print(f"        · {s}")
print(f"  步骤2 标题定级：h1={lvl_cnt[1]} h2={lvl_cnt[2]} h3={lvl_cnt[3]} "
      f"h4={lvl_cnt[4]} h5={lvl_cnt[5]} h6={lvl_cnt[6]}")
print(f"        其中 (X)/（X） 小标题 → h5：{n_paren} 个")
for s in paren_s:
    print(f"        · {s}")
print(f"  步骤3 无序号标题 ← 目录回填序号并定级：{n_recover} 个")
for s in recover_s:
    print(f"        · {s}")
print(f"  步骤4 无序号且目录亦无序号 → 保持原样：{n_keep} 个")
if n_keep and keep_s:
    print("        样例（多为 MinerU 丢失序号的正文小节，需人工补级）：")
    for s in keep_s:
        print(f"        · {s}")
print(f"  附   删除 <details> 图片描述块：{len(det_types)} 个")
for t, c in Counter(det_types).most_common():
    print(f"        · {t}: {c}")
print("-" * 66)
print(f"  目录序号映射条目：{len(toc_map)}    字符数 {len(raw)} → {len(result)}（Δ {len(result) - len(raw)}）")

if MODE == "apply":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(result, encoding="utf-8", newline="")
    print(f"  ✔ 已写出：{OUT}")
else:
    print("  (dry run — 未写文件；命令末尾加 apply 执行)")
