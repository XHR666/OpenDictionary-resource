#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fetch_restricted_wordlists.py — 采集"许可存疑/抓取来源"的考试词表（仅本地 work/，不入库）

用途：把判定为"不可分发"的词库先采集到本地，合并成大库；
      但**绝不进 APK**，须用户在 App 内明确授权并知风险后，从资源仓（GitHub Releases）下载。
      本脚本只负责采集到本地工作区；发布与授权流程见 docs/proj/07-受限词典包与下载授权.md。

来源与风险（2026-10-22 调研）：
  - qwerty-learner（GPL-3.0 代码；词库来自 kajweb/爬取，含 BEC/GMAT/SAT/TEM4/TEM8）：风险=高
  - mahavivo/english-wordlists（无 LICENSE；专四/专八/高中/中考表，来源不明）：风险=高
  - KyleBing/english-vocabulary（BSD-3 代码；词库为 kajweb 下游）：风险=中高
产物（均本地）：work/external_restricted/raw/*、restricted-tags.csv、SOURCES.json
用法：python3 scripts/fetch_restricted_wordlists.py --fetch | --self-test
"""
import argparse, base64, csv, json, os, sys, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "work", "external_restricted")
UA = {"User-Agent": "OpenDictionary-restricted-fetch/0.1 (local only)"}

SOURCES = {
    "tem4_qwerty": {"repo": "RealKai42/qwerty-learner", "path": "public/dicts/Level4luan_2_T.json",
                    "tag": "tem4", "license": "GPL-3.0(repo only)", "risk": "高", "note": "词库抓取自商业 App/网站，仓库许可仅覆盖代码"},
    "tem8_qwerty": {"repo": "RealKai42/qwerty-learner", "path": "public/dicts/Level8luan_2_T.json",
                    "tag": "tem8", "license": "GPL-3.0(repo only)", "risk": "高", "note": "同上"},
    "bec_qwerty2": {"repo": "RealKai42/qwerty-learner", "path": "public/dicts/BEC_2_T.json",
                    "tag": "bec", "license": "GPL-3.0(repo only)", "risk": "高", "note": "同上"},
    "bec_qwerty3": {"repo": "RealKai42/qwerty-learner", "path": "public/dicts/BEC_3_T.json",
                    "tag": "bec", "license": "GPL-3.0(repo only)", "risk": "高", "note": "同上"},
    "gmat_qwerty": {"repo": "RealKai42/qwerty-learner", "path": "public/dicts/GMAT_3_T.json",
                    "tag": "gmat", "license": "GPL-3.0(repo only)", "risk": "高", "note": "同上"},
    "sat_qwerty": {"repo": "RealKai42/qwerty-learner", "path": "public/dicts/SAT_3_T.json",
                   "tag": "sat", "license": "GPL-3.0(repo only)", "risk": "高", "note": "同上"},
    "tem4_mahavivo": {"repo": "mahavivo/english-wordlists", "path": "英语专业四八级词汇表.txt",
                      "tag": "tem4", "license": "无 LICENSE", "risk": "高", "note": "上游来源不明，无可证明许可"},
    "tem8_mahavivo": {"repo": "mahavivo/english-wordlists", "path": "英语专业星标八级词汇.txt",
                      "tag": "tem8", "license": "无 LICENSE", "risk": "高", "note": "同上"},
    "gk_mahavivo": {"repo": "mahavivo/english-wordlists", "path": "Highschool_edited.txt",
                    "tag": "gk", "license": "无 LICENSE", "risk": "高", "note": "同上"},
}


def api_get(path):
    req = urllib.request.Request("https://api.github.com" + path, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_text(repo, path):
    d = api_get("/repos/%s/contents/%s" % (repo, urllib.parse.quote(path)))
    if d.get("encoding") == "base64":
        return base64.b64decode(d["content"]).decode("utf-8", "replace")
    # >1MB：contents API 不返回内容，raw.githubusercontent 部分网络不可达 → 用 git sparse clone 兜底
    return git_sparse_get(repo, path)


_CLONES = {}


def git_sparse_get(repo, path):
    import subprocess, shutil, tempfile
    key = (repo, os.path.dirname(path))
    if key not in _CLONES:
        tmp = tempfile.mkdtemp(prefix="ods-fetch-")
        url = "https://github.com/%s.git" % repo
        subprocess.run(["git", "clone", "--depth", "1", "--filter=blob:none", "--sparse", url, tmp],
                       check=True, capture_output=True, timeout=240)
        subprocess.run(["git", "-C", tmp, "sparse-checkout", "set", os.path.dirname(path)],
                       check=True, capture_output=True, timeout=120)
        _CLONES[key] = tmp
    with open(os.path.join(_CLONES[key], path), "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def parse_qwerty(text):
    """qwerty 词表 JSON 结构兼容：list[{name/headWord/word}] 或 dict{...}；取单词字段。"""
    data = json.loads(text)
    items = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                items = v
                break
    words = []
    for it in items:
        if isinstance(it, str):
            w = it
        elif isinstance(it, dict):
            w = it.get("name") or it.get("headWord") or it.get("word") or it.get("text") or ""
        else:
            w = ""
        w = (w or "").strip()
        if w:
            words.append(w)
    return words


def parse_plain(text):
    return [ln.strip() for ln in text.splitlines()
            if ln.strip() and not ln.strip().startswith("#") and len(ln.strip()) < 80]


def fetch_all():
    import urllib.parse  # noqa: F401（供 quote 使用）
    os.makedirs(os.path.join(OUT, "raw"), exist_ok=True)
    meta = {"fetched_at": None, "sources": {}}
    from datetime import datetime, timezone
    meta["fetched_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = []
    for key, src in SOURCES.items():
        text = fetch_text(src["repo"], src["path"])
        fn = key + (".json" if src["path"].endswith(".json") else ".txt")
        with open(os.path.join(OUT, "raw", fn), "w", encoding="utf-8") as f:
            f.write(text)
        words = parse_qwerty(text) if src["path"].endswith(".json") else parse_plain(text)
        meta["sources"][key] = {**{k: src[k] for k in ("repo", "path", "tag", "license", "risk", "note")},
                                "file": fn, "raw_words": len(words)}
        for w in words:
            rows.append((w.lower(), src["tag"], src["repo"], src["license"], src["risk"], src["note"]))
    # 去重（同 word+tag 保留第一条）
    seen, uniq = set(), []
    for r in rows:
        if (r[0], r[1]) not in seen:
            seen.add((r[0], r[1]))
            uniq.append(r)
    with open(os.path.join(OUT, "restricted-tags.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["word", "tag", "source", "license", "risk", "note"])
        w.writerows(uniq)
    counts = {}
    for r in uniq:
        counts[r[1]] = counts.get(r[1], 0) + 1
    meta["restricted_rows"] = len(uniq)
    meta["tag_counts"] = counts
    with open(os.path.join(OUT, "SOURCES.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    fail = []
    for need in ("tem4", "tem8", "bec", "gmat", "sat"):
        if counts.get(need, 0) < 100:
            fail.append("%s<100(%s)" % (need, counts.get(need, 0)))
    print(json.dumps({"restricted_rows": len(uniq), "tag_counts": counts}, ensure_ascii=False, indent=2))
    if fail:
        raise SystemExit("FAIL 判据: " + "; ".join(fail))
    print("OK 受限词表采集完成（仅本地 work/external_restricted）")
    return 0


def self_test():
    ok = fail = 0

    def chk(n, c):
        nonlocal ok, fail
        print(("PASS " if c else "FAIL ") + n)
        ok, fail = (ok + 1, fail) if c else (ok, fail + 1)

    q = json.dumps([{"name": "abandon"}, {"headWord": "ability"}, "able"])
    chk("qwerty 列表解析", len(parse_qwerty(q)) == 3)
    q2 = json.dumps({"data": [{"word": "run"}, {"word": "ran"}]})
    chk("qwerty dict 解析", parse_qwerty(q2) == ["run", "ran"])
    chk("纯文本解析", parse_plain("# c\napple\nbanana\n") == ["apple", "banana"])
    print("\n自检结果：%d 项通过，%d 项失败" % (ok, fail))
    return 0 if fail == 0 else 1


def main():
    ap = argparse.ArgumentParser(description="采集许可存疑词表（仅本地，不入库）")
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        sys.exit(self_test())
    if not args.fetch:
        ap.print_help(); return 2
    import urllib.parse  # noqa: F401
    sys.exit(fetch_all())


if __name__ == "__main__":
    main()
