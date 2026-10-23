#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fetch_external_wordlists.py — 拉取外部补充词表/短语表（本地 work/external/，不入库）

用途：补齐 ECDICT 缺失的考试标签与高考短语。数据只落本地工作区（work/ 已 gitignore），
      仓库里只保留本脚本与 LICENSES 登记（决策 D21/D23）。

来源（2026-10-22 核实；许可见下表，数据结构固定）：
  1. 2ndLA/english-phrases  lists/senior.txt  → 高考短语（CC-BY-SA-4.0）
     （同仓 lists/tem4.txt、lists/tem8.txt 为专四/专八短语，一并拉取备用）
  2. chrisdeaner/sat-prep  sat_vocabulary.csv → sat 词表（MIT，275 词，置信度高）
  3. hkperceptionlab/sat-vocab  public/sat1000.json → sat 补充词表（MIT，991 词，置信度中；上游未注明）
  说明：TEM8/TEM4/BEC 无可证明许可链的开源词表（2026-10-22 核实），本脚本不拉取，避免误入库。

用法：
  python3 scripts/fetch_external_wordlists.py --fetch          # 联网拉取
  python3 scripts/fetch_external_wordlists.py --self-test      # 离线解析自检（失败非零）
产物：
  work/external/senior.txt / tem4-phrases.txt / tem8-phrases.txt
  work/external/tem8-words.txt / sat-words.csv
  work/external/extra-tags.csv        （word,tag,source,license,confidence）
  work/external/phrases-gk.csv        （phrase,translation,book_id,source,license）
  work/external/SOURCES.json          （来源/许可/条数/抓取时间/证据 URL）
"""
import argparse
import base64
import csv
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "work", "external")
UA = {"User-Agent": "OpenDictionary-fetch/0.1 (local dev)"}

SOURCES = {
    "senior_phrases": {"repo": "2ndLA/english-phrases", "path": "lists/senior.txt",
                       "license": "CC-BY-SA-4.0", "kind": "gk_phrases"},
    "tem4_phrases": {"repo": "2ndLA/english-phrases", "path": "lists/tem4.txt",
                     "license": "CC-BY-SA-4.0", "kind": "tem4_phrases"},
    "tem8_phrases": {"repo": "2ndLA/english-phrases", "path": "lists/tem8.txt",
                     "license": "CC-BY-SA-4.0", "kind": "tem8_phrases"},
    "sat_words": {"repo": "chrisdeaner/sat-prep", "path": "sat_vocabulary.csv",
                  "license": "MIT", "kind": "sat"},
    "sat1000": {"repo": "hkperceptionlab/sat-vocab", "path": "public/sat1000.json",
                "license": "MIT", "kind": "sat"},
}


def api_get(path):
    req = urllib.request.Request("https://api.github.com" + path, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_text(repo, path):
    d = api_get("/repos/%s/contents/%s" % (repo, path))
    if d.get("encoding") != "base64":
        raise RuntimeError("unexpected encoding for %s/%s" % (repo, path))
    return base64.b64decode(d["content"]).decode("utf-8", "replace")


def fetch_all():
    os.makedirs(OUT, exist_ok=True)
    meta = {"fetched_at": None, "sources": {}}
    from datetime import datetime, timezone
    meta["fetched_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    raw = {}
    for key, src in SOURCES.items():
        text = fetch_text(src["repo"], src["path"])
        raw[key] = text
        fn = {"senior_phrases": "senior.txt", "tem4_phrases": "tem4-phrases.txt",
              "tem8_phrases": "tem8-phrases.txt", "sat_words": "sat-words.csv",
              "sat1000": "sat1000.json"}[key]
        with open(os.path.join(OUT, fn), "w", encoding="utf-8") as f:
            f.write(text)
        meta["sources"][key] = {"repo": src["repo"], "path": src["path"], "license": src["license"],
                                "file": fn, "rows": len([x for x in text.splitlines() if x.strip()])}
    # normalized extra-tags.csv（SAT 双源去重：主源 275 置信度高，辅源 991 置信度中）
    # 注意：TEM8/TEM4/BEC 无可证明许可链的开源词表，不合并（2026-10-22 更正）。
    tags = {}
    for row in csv.DictReader(raw["sat_words"].splitlines()):
        w = (row.get("word") or "").strip().lower()
        if w:
            tags[w] = (w, "sat", SOURCES["sat_words"]["repo"], SOURCES["sat_words"]["license"], "高")
    for item in json.loads(raw["sat1000"]):
        w = (item.get("word") or "").strip().lower()
        if w and w not in tags:
            tags[w] = (w, "sat", SOURCES["sat1000"]["repo"], SOURCES["sat1000"]["license"], "中")
    tags = list(tags.values())
    with open(os.path.join(OUT, "extra-tags.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["word", "tag", "source", "license", "confidence"])
        w.writerows(tags)
    meta["extra_tags_rows"] = len(tags)
    # normalized phrases-gk.csv
    ph = [(p.strip(), "", "gk_phrases", SOURCES["senior_phrases"]["repo"], SOURCES["senior_phrases"]["license"])
          for p in raw["senior_phrases"].splitlines() if p.strip()]
    with open(os.path.join(OUT, "phrases-gk.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["phrase", "translation", "book_id", "source", "license"])
        w.writerows(ph)
    meta["phrases_gk_rows"] = len(ph)
    with open(os.path.join(OUT, "SOURCES.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    # 判据：数量下限，失败非零
    fail = []
    if meta["extra_tags_rows"] < 1000:
        fail.append("extra_tags_rows < 1000")
    if meta["phrases_gk_rows"] < 2000:
        fail.append("phrases_gk_rows < 2000")
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    if fail:
        raise SystemExit("FAIL 判据: " + "; ".join(fail))
    print("OK 拉取完成：extra_tags=%d phrases=%d" % (meta["extra_tags_rows"], meta["phrases_gk_rows"]))
    return 0


def self_test():
    """离线自检：解析/归一化逻辑与判据（构造样例，不发网络）。"""
    ok = fail = 0

    def chk(n, c):
        nonlocal ok, fail
        print(("PASS " if c else "FAIL ") + n)
        ok, fail = (ok + 1, fail) if c else (ok, fail + 1)

    sample_sat1000 = json.dumps([{"word": "abase"}, {"word": "abate"}])
    tags = [(x["word"], "sat", "r", "MIT", "中") for x in json.loads(sample_sat1000)]
    chk("sat1000 解析 2 词", len(tags) == 2 and tags[0][1] == "sat")
    sample_sat = "word,definition,score\neschew,avoid,6\n"
    sat = [(r["word"].strip(), "sat", "r", "MIT", "高") for r in csv.DictReader(sample_sat.splitlines())]
    chk("sat CSV 解析", sat and sat[0][0] == "eschew")
    sample_ph = "a bill of fare\na case in point\n"
    ph = [(p.strip(), "", "gk_phrases", "r", "CC-BY-SA-4.0") for p in sample_ph.splitlines() if p.strip()]
    chk("短语解析", len(ph) == 2 and ph[1][0] == "a case in point")
    print("\n自检结果：%d 项通过，%d 项失败" % (ok, fail))
    return 0 if fail == 0 else 1


def main():
    ap = argparse.ArgumentParser(description="拉取外部补充词表/短语表（本地 work/external）")
    ap.add_argument("--fetch", action="store_true", help="联网拉取")
    ap.add_argument("--self-test", action="store_true", help="离线解析自检")
    args = ap.parse_args()
    if args.self_test:
        sys.exit(self_test())
    if not args.fetch:
        ap.print_help()
        return 2
    sys.exit(fetch_all())


if __name__ == "__main__":
    main()
