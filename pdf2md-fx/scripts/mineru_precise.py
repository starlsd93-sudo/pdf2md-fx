#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MinerU 精准解析 API 客户端（A 类·复制自 mineru-pdf-parse）。
v4 批量接口：POST /file-urls/batch -> PUT 上传 -> GET 轮询 -> 下载 zip 解压。
需 token（项目根 {Key}MinerU_API.txt）。单文件 ≤200MB/≤200 页；分批见 pdf_utils.py。
输出每个文件一个子目录：full.md + images/ + content_list.json + layout.json。

用法同 mineru-pdf-parse：
  python mineru_precise.py FILE [FILE ...] [--out DIR] [--lang ch] [--model vlm]
                           [--ocr] [--pages "1-10"] [--check-key]
"""
import argparse, base64, json, sys, time, zipfile, io
from datetime import datetime, timezone
from pathlib import Path
import requests

API_BASE = "https://mineru.net/api/v4"
KEY_FILENAME = "{Key}MinerU_API.txt"
EXPIRY_WARN_DAYS = 7


def _log(m): print(m, flush=True)


def find_key_file(explicit):
    if explicit:
        p = Path(explicit)
        if not p.is_file():
            sys.exit(f"[KEY] 指定的 Key 文件不存在：{p}")
        return p
    here = Path.cwd()
    for d in [here, *here.parents]:
        cand = d / KEY_FILENAME
        if cand.is_file():
            return cand
    sys.exit(f"[KEY] 未找到 {KEY_FILENAME}。请放在项目根目录，或用 --key 指定。")


def read_token(key_path):
    for line in key_path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            return s
    sys.exit(f"[KEY] {key_path} 无 token（第一行非 # 内容）。")


def decode_jwt_exp(token):
    try:
        b = token.split(".")[1]; b += "=" * (-len(b) % 4)
        return json.loads(base64.urlsafe_b64decode(b)).get("exp")
    except Exception:
        return None


def check_expiry(token, key_path):
    exp = decode_jwt_exp(token)
    if exp is None:
        _log("[KEY] 警告：无法解析 exp，跳过有效期检查。"); return None
    days = (exp - datetime.now(timezone.utc).timestamp()) / 86400.0
    ed = datetime.fromtimestamp(exp, tz=timezone.utc).strftime("%Y-%m-%d")
    if days <= 0:
        _log("=" * 60); _log(f"[KEY] X Token 已于 {ed} 过期！请到 https://mineru.net/apiManage 续期并更新 Key。"); _log("=" * 60)
        sys.exit(2)
    if days <= EXPIRY_WARN_DAYS:
        _log("=" * 60); _log(f"[KEY] ! Token 将于 {ed} 过期，仅剩 {days:.1f} 天，建议尽快续期。"); _log("=" * 60)
    else:
        _log(f"[KEY] OK - token 有效，到期 {ed}（剩 {days:.0f} 天）。")
    return days


def headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def request_upload_urls(token, files, opts):
    body = {"enable_formula": opts["enable_formula"], "enable_table": opts["enable_table"],
            "language": opts["lang"], "model_version": opts["model"],
            "files": [{"name": f.name, "is_ocr": opts["ocr"]} for f in files]}
    if opts["pages"]:
        for fe in body["files"]:
            fe["page_ranges"] = opts["pages"]
    r = requests.post(f"{API_BASE}/file-urls/batch", headers=headers(token), json=body, timeout=60)
    r.raise_for_status(); data = r.json()
    if data.get("code") != 0:
        sys.exit(f"[API] 申请上传URL失败：{data.get('code')} {data.get('msg')}")
    return data["data"]["batch_id"], data["data"]["file_urls"]


def poll_results(token, batch_id, poll, timeout):
    url = f"{API_BASE}/extract-results/batch/{batch_id}"
    deadline = time.time() + timeout; last = {}
    while time.time() < deadline:
        data = requests.get(url, headers=headers(token), timeout=60).json()
        if data.get("code") != 0:
            sys.exit(f"[API] 查询失败：{data.get('code')} {data.get('msg')}")
        results = data["data"].get("extract_result", [])
        states = {i.get("file_name", "?"): i.get("state", "?") for i in results}
        if states != last:
            _log(f"[POLL] {states}"); last = states
        if results and all(i.get("state") in ("done", "failed") for i in results):
            return results
        time.sleep(poll)
    sys.exit(4)


def download_and_extract(results, out_root):
    out_root.mkdir(parents=True, exist_ok=True); ok, failed = [], []
    for item in results:
        name = item.get("file_name", "file"); stem = Path(name).stem
        if item.get("state") != "done":
            failed.append((name, item.get("err_msg", ""))); _log(f"[FAIL] {name}: {item.get('err_msg','')}"); continue
        zip_url = item.get("full_zip_url")
        if not zip_url:
            failed.append((name, "no zip")); continue
        _log(f"[DL] {name}")
        r = requests.get(zip_url, timeout=600); r.raise_for_status()
        dest = out_root / stem; dest.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            zf.extractall(dest)
        _log(f"[OK] -> {dest}"); ok.append(dest)
    return ok, failed


def main():
    ap = argparse.ArgumentParser(description="MinerU 精准解析 API 客户端")
    ap.add_argument("files", nargs="*")
    ap.add_argument("--key", default=None); ap.add_argument("--out", default=None)
    ap.add_argument("--lang", default="ch"); ap.add_argument("--model", default="vlm", choices=["pipeline", "vlm"])
    ap.add_argument("--no-formula", action="store_true"); ap.add_argument("--no-table", action="store_true")
    ap.add_argument("--ocr", action="store_true"); ap.add_argument("--pages", default=None)
    ap.add_argument("--poll", type=int, default=10); ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--check-key", action="store_true")
    args = ap.parse_args()
    token = read_token(find_key_file(args.key)); check_expiry(token, find_key_file(args.key))
    if args.check_key:
        return 0
    if not args.files:
        sys.exit("[ARG] 未提供文件。")
    paths = [Path(f) for f in args.files]
    for p in paths:
        if not p.is_file():
            sys.exit(f"[ARG] 文件不存在：{p}")
    if len(paths) > 50:
        sys.exit("[ARG] 单次最多 50 个文件。")
    out_root = Path(args.out) if args.out else paths[0].parent / "_mineru_out"
    opts = {"lang": args.lang, "model": args.model, "enable_formula": not args.no_formula,
            "enable_table": not args.no_table, "ocr": args.ocr, "pages": args.pages}
    _log(f"[1/4] 申请上传 URL（{len(paths)} 文件 model={args.model} formula={opts['enable_formula']}）")
    batch_id, urls = request_upload_urls(token, paths, opts)
    _log(f"      batch_id={batch_id}")
    _log("[2/4] 上传…")
    for p, u in zip(paths, urls):
        _log(f"      PUT {p.name}")
        with open(p, "rb") as fh:
            requests.put(u, data=fh, timeout=600).raise_for_status()
    _log(f"[3/4] 轮询（每 {args.poll}s）…")
    results = poll_results(token, batch_id, args.poll, args.timeout)
    _log("[4/4] 下载解压…")
    ok, failed = download_and_extract(results, out_root)
    _log("=" * 60); _log(f"完成：成功 {len(ok)}，失败 {len(failed)}。输出 -> {out_root}")
    return 3 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
