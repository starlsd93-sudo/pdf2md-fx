---
name: pdf2md-fx
description: PDF → Markdown 一体化枢纽，智能路由两类任务：A 格式化存档/含公式精读（MinerU 精准 API，含图+公式+分批拼接+图片本地化+Typora 超大文件自动分节）、B 临时阅读·纯文字（本地分栏合并或 MinerU 轻量 API，节约 token，不含公式）。自动判断调用来源（其它 skill 调用 vs 用户直接调用）并路由，含公式任务强制使用精准 API（轻量 API 经实测会错认希腊字母、产生字符间距错误）。触发词：PDF转MD、解析PDF、提取文献、PDF存档、临时阅读PDF、提取公式、PDF转Markdown、MinerU、参考文献数字化、读论文、章节资料数字化。
metadata:
  version: "1.3"
  last-updated: "2026-06-04"
---

# pdf2md-fx — PDF→MD 二模式枢纽 v1.3

把 PDF 转成 Markdown 的一体化 skill，**自包含**（已复制 mineru-pdf-parse 的精准/轻量 API 客户端与 mineru-img-convert 的图片本地化逻辑，不依赖外部 skill）。

---

## ⛔ 第一步：强制暂停，判断调用来源并路由

**进入本 skill 后，未完成路由判断前不得执行任何解析。**

### 场景 1：由其它 skill（如 literature-knowledge-base、thesis-writing）调用

根据调用方传入的任务描述**自动判断**，无需询问用户：

| 调用意图 | 路由 | 依据 |
|---|---|---|
| 综述研究现状 / 概括方法 / 提取实验数值 / 文字总结 | → **模式 B** | 纯文字数值，无需精确公式 |
| 借鉴理论推导 / 对比公式正确性 / 提取 LaTeX 表达式 | → **模式 A** | 含公式必须精准 API，轻量 API 经实测会错认希腊字母（如 Λ→A）、产生字符间距错误，**禁止使用** |

### 场景 2：用户直接调用

**必须用 AskUserQuestion 二选一**，再按对应模式执行：

| 选项 | 路由 | 适合场景 |
|---|---|---|
| **书籍/文献存档**（长期入库，图表公式详细准确） | → **模式 A** | 参考书籍数字化、需反复查阅的核心文献 |
| **文献快速总结**（只看文字结论/数值，节约 token） | → **模式 B** | 快速了解研究背景、批量筛选文献 |

---

## 前置：API Key 检查（模式 A 专用，模式 B 跳过）

**每次执行模式 A 前，先检查 Key 是否存在且有效。**

1. 检查项目根目录是否存在 `{Key}MinerU_API.txt`（含大括号的文件名，已在 `.gitignore` 中，**不会被 git 同步**）。
2. **若文件不存在**：立即暂停，提示用户：
   > `{Key}MinerU_API.txt` 未找到。请前往 **https://mineru.net/apiManage/token** 免费申请 token，将 token 粘贴为文件第一行，保存到项目根目录 `{Key}MinerU_API.txt`。该文件已在 `.gitignore` 中，**不会被 git 同步，无安全风险**。
3. **若文件存在**：执行 `python $S/mineru_precise.py --check-key` 校验有效期（脚本自动读取项目根 Key 文件）。剩余 ≤7 天时醒目提示续期。
4. Key 有效后，继续执行模式 A 步骤。

---

## 模式 A：格式化存档 / 含公式精读（精准 API）

> 适用：书籍/文献持久化存档、含公式理论推导借鉴、需要图表的深度精读。
> 引擎：MinerU 精准 API（VLM 模型，zip 返回 md+图，含 LaTeX 公式与 HTML 表格）。

1. **探测页数**（本地，最省 token）：
   `python $S/pdf_utils.py probe "<pdf>"` → 取 `pages`。
2. **分批**（仅当 > 200 页）：建临时目录 `tmp/`，按 **193 页/批**（留 7 页裕度，精准 API 上限 200）：
   `python $S/pdf_utils.py split "<pdf>" --batch 193 --tmp "<dir>/_mineru_out/_tmp"`
   ≤200 页则跳过，单文件直接解析。
3. **精准解析**：对每个分卷（或原文件）逐批上传，**串行**执行（避免超出日限额）：
   `python $S/mineru_precise.py <各分卷.pdf> --out "<dir>/_mineru_out" --lang <见语言速查>`
   （含公式默认 LaTeX、表格 HTML、model=vlm）。
4. **拼接 + 校验衔接**（多批时）：
   `python $S/merge_md.py --root "<dir>/_mineru_out" --stem "<pdf名>" --out "<dir>/_mineru_out/_merged"`
   → 产 `merged.md` + 合并 `images/` + `_merge_report.json`。
   **人工抽查各 `BATCH BOUNDARY` 处上下文是否语义连续**（报告含每批 head/tail）。单批则直接用该批 full.md/images，跳过此步。
5. **图片本地化 → 落目标目录**（相对化 + 丢未引用图 + 图号语义重命名）：
   先 dry run：`python $S/img_localize.py --md "<merged.md>" --images "<images/>" --out "<目标目录>" --title "<文献名>"`
   确认 mapping 后加 `apply`。
   → 最终 `<目标目录>/<文献名>.md` + `<目标目录>/img-<文献名>/`；
     过程文件（zip 解压、`_merged/` 等）留在 `_mineru_out/`。
6. **MinerU 后处理修正（v1.3，学位论文/书籍强烈建议）**：前提是 MinerU 不漏标题、只是层级/序号错乱，据此分四步修订（含删图片描述块）：
   - **步骤1 目录区误标题还原**：以「目录」标题为起点、其后第一个「干净标题」（无点引线页码尾，通常是『图清单』或正文首个『第X章』）为终点，区间内所有 `#` 行都是目录条目 → 去 `#` 还原为正文；另对全文任何带「点引线+页码」尾的 `#` 行一并还原。
   - **步骤2 按序号定级 + 删描述块**：`第X章`→h1 / `X.X`→h2 / `X.X.X`→h3 / `X.X.X.X`→h4（按小数点段数定级，封顶 h6）；`(X)`/`（X）` 半全角括号数字小标题→**h5**；并删除每张图后 MinerU 注入的 `<details><summary>类型</summary>…</details>` 图片描述块（text_image / natural_image / flowchart 等约 17 种 AI 英文图注）。
   - **步骤3 无序号标题回填目录序号**：先解析目录区建立『标题文字→序号』映射；正文无序号标题若能在目录里找到同名带序号条目，则把序号补进标题并按序号定级（如 `# 研究背景` + 目录『1.1 研究背景』→ `## 1.1 研究背景`）。
   - **步骤4 目录也无序号 → 保持原样**：级别不动，留待人工处理，报告中列出样例数量。
   先 dry run 看报告：`python $S/mineru_postfix.py --md "<目标目录>/<文献名>.md"`
   核对「锚点目录区 / 步骤1还原数 / 各级标题数与(X)→h5数 / 步骤3回填数 / 步骤4保持原样样例 / 描述块类型分布」无误后加 `apply` 原地修正（或 `--out` 写新文件）。
   > **已知限制**：① 若该论文目录与正文小节都丢了序号（MinerU 整篇未转出 `x.x`），步骤3/4 无源可补，小节保持 h1（如贺志远），需人工补级。② 超长章标题偶被断成两个 `#` 行（如 `# 第二章 …综合与` + `# TriMule…`），本步不自动合并。
7. **超大文件拆分（Typora 适配）**：Typora 默认硬限 **2 MB**，若最终 MD > **1.5 MB** 则自动拆分：
   检查：`python $S/split_md.py --md "<目标目录>/<文献名>.md" --out "<目标目录>" --title "<文献名>" --check-only`
   → exit 0 = 无需；exit 1 = 需要拆分，执行：
   `python $S/split_md.py --md "<目标目录>/<文献名>.md" --out "<目标目录>" --title "<文献名>"`
   → 产出 `<文献名>_Part01.md` … `<文献名>_PartNN.md`，共享同一 `img-<文献名>/` 文件夹；
     原合并 MD 移至 `_mineru_out/_merged/merged_full.md`。
   > **经验值**：精准 API 每 193 页约产出 500–650 KB；≤400 页（2 批）通常无需拆；1060 页（6 批）= ~3.1 MB 须拆。

---

## 模式 B：临时阅读·纯文字（不含公式）

> 适用：快速总结文献结论、提取实验数值、研究现状综述。不含公式，节约 token，无需 API Key。
> 引擎：文字型→本地原生分栏合并（0 Claude token）；图片型→MinerU 轻量 API（免 token）。

1. **探测 PDF 类型**：`python $S/pdf_utils.py probe "<pdf>"` → `type` / `is_ocr`。
2. **文字型**（type=text，is_ocr=False）→ 本地分栏合并，亚秒完成：
   `python $S/local_read.py "<pdf>" --out "<目标目录>/<pdf名>.md"`
   （自动判单/双栏并按列重排；大文件用 `--max-chars N` 截断后分批喂入）。
3. **图片型**（is_ocr=True）→ MinerU 轻量 API，分批 20 页：
   `python $S/pdf_utils.py split "<pdf>" --batch 20 --tmp "<目标目录>/_mineru_out/_tmp"`
   `python $S/mineru_light.py <各分卷.pdf> --out "<目标目录>/_mineru_out/_proc" --lang <见下> --ocr`
   归位：`python $S/concat_parts.py --proc "<目标目录>/_mineru_out/_proc" --dest "<目标目录>" --all`
   → 分批合并 md / 单篇 md 落目标目录；part md 留 `_mineru_out/_proc`。

> **注意**：模式 B 轻量 API **不保证公式正确性**（实测：`\boldsymbol{\Lambda}` 被误识别为 `\mathbf{A}`，约束矩阵符号错误；subscript 文字被拆为字母间距如 `\mathrm{g l o b a l}`）。若任务需要公式，**必须切换至模式 A**。

---

## 输出布局（v1.1）

- **最终 md 一律落「目标目录」**：
  - 模式 A ≤1.5 MB → 单文件 `<文献名>.md`；> 1.5 MB → `<文献名>_Part01.md` … `<文献名>_PartNN.md`（共享 `img-<文献名>/`）
  - 模式 B → 单文件（图片型分批后合并）落目标目录
- **`_mineru_out/` 只放过程文件**：临时分卷 PDF、精准解析 zip 解压产物、`_merged/`、超大书的 `merged_full.md`、轻量 API 的 `_proc/` part md。

---

## language 速查（OCR 才生效；文字型抽文字层用 ch 即可）

| 文献语言 | 代码 | 文献语言 | 代码 |
|---|---|---|---|
| 中文/中英混 | `ch` | 德/法等拉丁 | `latin` |
| 纯英文 | `en` | 俄/乌等西里尔 | `east_slavic` |

图片型德/俄用 ch 会变音丢失/西里尔乱码 → 必须 `latin`/`east_slavic`（实测验证）。

---

## 决策树速记

```
调用来源？
├── 其它 skill 调用
│   ├── 需要公式？ → 模式 A（精准 API，必须）
│   └── 只要文字/数值？ → 模式 B（本地/轻量，节约 token）
└── 用户直接调用
    ├── 书籍/文献长期存档？ → 模式 A（精准，图表公式详细）
    └── 快速总结/批量筛选？ → 模式 B（轻量，节约 token）
```

---

## 前置条件

- **模式 A** 需 Key：项目根 `{Key}MinerU_API.txt`（**gitignore，不会被 git 同步**，90 天有效）。申请地址：https://mineru.net/apiManage/token
- **模式 B** 无需 Key，完全免费。
- 依赖：`pip install pypdf pdfminer.six requests`。
- 额度：精准 API 1000 页/天高优先级，单文件 ≤200MB/≤200 页；轻量 API 单文件 ≤10MB/≤20 页。

---

## 脚本清单（scripts/）

| 脚本 | 用途 | 用于 |
|---|---|---|
| `pdf_utils.py` | probe（页数/类型）+ split（分批） | A/B |
| `mineru_precise.py` | 精准 API（zip：md+图，需 Key；`--check-key` 校验有效期） | A |
| `merge_md.py` | 多批 md 拼接 + images 合并 + 衔接校验报告 | A |
| `img_localize.py` | 图片相对化 + 丢未引用图 + 图号语义重命名 | A |
| `mineru_postfix.py` | 后处理修正（4步）：目录区误标题还原 + 按序号定级((X)→h5) + 目录回填序号 + 删图片描述块（v1.3） | A |
| `split_md.py` | 超大 MD 按 BATCH BOUNDARY 拆分（Typora 2MB 适配）；`--check-only` 仅判断 | A |
| `local_read.py` | 本地字符级分栏判断与合并 | B（文字型） |
| `mineru_light.py` | 轻量 API（免 Key，仅回 md，勿用于公式） | B（图片型） |
| `concat_parts.py` | 归位：分批合并/单篇移动到目标目录，part 留过程 | B（图片型） |
