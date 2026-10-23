#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_phrase_library.py — 构建短语/习语/拉丁语短语库（本地 work/external/phrase-library.csv）

数据来源：
  1. ECDICT 多词条目（过滤后）→ book_id=phrases_ecdict，kind=phrase，MIT（数据链待法务）
  2. 2ndLA/english-phrases：senior.txt → gk_phrases；tem4/tem8 短语 → tem4_phrases/tem8_phrases（CC BY-SA 4.0）
  3. scripts/data/latin-phrases.csv（项目自编，CC0）→ latin_phrases，kind=latin

判据：短语行数 > 20000；latin ≥ 40；gk_phrases ≥ 2000；输出不含空短语/重复（同 book 内）。
用法：python3 scripts/build_phrase_library.py --build | --self-test
"""
import argparse, csv, os, re, sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ECDICT = os.path.join(ROOT, "work", "ECDICT", "ecdict.csv")
EXT = os.path.join(ROOT, "work", "external")
LATIN = os.path.join(ROOT, "scripts", "data", "latin-phrases.csv")
OUT = os.path.join(EXT, "phrase-library.csv")
TOKEN = re.compile(r"^[a-z][a-z'\-]*$")
MIN_ROWS = 20000


def norm(w):
    return " ".join((w or "").strip().lower().split())


def ecdict_phrases(csv_path):
    rows = []
    if not os.path.isfile(csv_path):
        return rows
    with open(csv_path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            w = norm(r.get("word"))
            tr = (r.get("translation") or "").strip().replace("\n", "；")
            if not w or not tr:
                continue
            toks = w.split()
            if not (2 <= len(toks) <= 4) or len(w) > 40:
                continue
            if not all(TOKEN.match(t) for t in toks):
                continue
            if w[0] == "'":
                continue
            rows.append((w, tr[:120], "phrases_ecdict", "phrase", "ECDICT", "MIT(数据链待核)"))
    # 去重（保留第一条）
    seen, out = set(), []
    for r in rows:
        if r[0] in seen:
            continue
        seen.add(r[0])
        out.append(r)
    return out


def list_phrases(path, book, kind, source, license_):
    if not os.path.isfile(path):
        return []
    out = []
    for line in open(path, encoding="utf-8"):
        p = norm(line)
        if p and len(p) <= 80:
            out.append((p, "", book, kind, source, license_))
    return out


def latin_phrases(path):
    if not os.path.isfile(path):
        return []
    out = []
    for r in csv.DictReader(open(path, encoding="utf-8")):
        p = norm(r.get("phrase"))
        if p:
            out.append((p, (r.get("translation") or "").strip(), "latin_phrases", "latin",
                        "project-curated", "CC0-1.0"))
    return out


def build():
    rows = []
    rows += ecdict_phrases(ECDICT)
    rows += list_phrases(os.path.join(EXT, "senior.txt"), "gk_phrases", "phrase",
                         "2ndLA/english-phrases", "CC-BY-SA-4.0")
    rows += list_phrases(os.path.join(EXT, "tem4-phrases.txt"), "tem4_phrases", "phrase",
                         "2ndLA/english-phrases", "CC-BY-SA-4.0")
    rows += list_phrases(os.path.join(EXT, "tem8-phrases.txt"), "tem8_phrases", "phrase",
                         "2ndLA/english-phrases", "CC-BY-SA-4.0")
    rows += latin_phrases(LATIN)
    # 同 book 去重；保留非空译文优先
    best = {}
    for r in rows:
        key = (r[2], r[0])
        if key not in best or (not best[key][1] and r[1]):
            best[key] = r
    rows = list(best.values())
    rows.sort(key=lambda r: (r[2], r[0]))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["phrase", "translation", "book_id", "kind", "source", "license"])
        w.writerows(rows)
    by_book = Counter(r[2] for r in rows)
    by_kind = Counter(r[3] for r in rows)
    print({"total": len(rows), "by_book": dict(by_book), "by_kind": dict(by_kind)})
    fail = []
    if len(rows) < MIN_ROWS:
        fail.append("total<%d" % MIN_ROWS)
    if by_kind.get("latin", 0) < 40:
        fail.append("latin<40")
    if by_book.get("gk_phrases", 0) < 2000:
        fail.append("gk_phrases<2000")
    if fail:
        raise SystemExit("FAIL 判据: " + "; ".join(fail))
    print("OK 短语库构建完成：%s" % OUT)
    return 0


def self_test():
    ok = fail = 0

    def chk(n, c):
        nonlocal ok, fail
        print(("PASS " if c else "FAIL ") + n)
        ok, fail = (ok + 1, fail) if c else (ok, fail + 1)

    chk("归一化", norm("  Run   Out  ") == "run out")
    chk("过滤规则：含数字拒绝", not all(TOKEN.match(t) for t in "800 number".split()))
    chk("过滤规则：正常短语通过", all(TOKEN.match(t) for t in "a case in point".split()))
    import tempfile
    tmp = tempfile.mkdtemp(prefix="od-phrase-")
    lp = os.path.join(tmp, "latin.csv")
    with open(lp, "w", encoding="utf-8") as f:
        f.write("phrase,translation,note\nde facto,事实上,\net cetera,等等,\n")
    ls = latin_phrases(lp)
    chk("latin 解析", len(ls) == 2 and ls[0][3] == "latin")
    pf = os.path.join(tmp, "p.txt")
    with open(pf, "w", encoding="utf-8") as f:
        f.write("a case in point\n\nby no means\n")
    pl = list_phrases(pf, "gk_phrases", "phrase", "src", "CC-BY-SA-4.0")
    chk("短语文件解析+去空行", len(pl) == 2 and pl[1][0] == "by no means")
    print("\n自检结果：%d 项通过，%d 项失败" % (ok, fail))
    return 0 if fail == 0 else 1


def main():
    ap = argparse.ArgumentParser(description="构建短语/习语/拉丁语短语库")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(self_test())
    if not a.build:
        ap.print_help(); return 2
    sys.exit(build())


if __name__ == "__main__":
    main()
