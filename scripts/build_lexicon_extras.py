#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_lexicon_extras.py — 构建"受限词表大库"（lexicon_extras.db，仅本地，不入 APK）

用途（用户 2026-10-22 要求）：把判定为"不可分发/许可存疑"的考试词表（TEM4/TEM8/BEC/GMAT/SAT 等）
合并成一个大数据库；**不进 APK**，用户须在 App 内明确授权并知风险后，从资源仓 Releases 下载。

产物（work/data/，work/ 已 gitignore，不提交）：
  lexicon_extras.db          受限词表库（word,tag,source,license,risk,note + meta）
  restricted-manifest.json   资源仓 manifest 片段（consent_required / risk_level / 不含词条数据）

判据（失败非零）：
  - 每个 tag 至少 100 条；总行数 > 10000；risk 只能是 中/高；meta.consent_required=true；
  - 输出库内不得出现空 word；重复 (word,tag) 必须去重。
用法：python3 scripts/build_lexicon_extras.py --self-test | --build
"""
import argparse
import csv
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "work", "external_restricted", "restricted-tags.csv")
OUT_DIR = os.path.join(ROOT, "work", "data")
DB = os.path.join(OUT_DIR, "lexicon_extras.db")
MANIFEST = os.path.join(OUT_DIR, "restricted-manifest.json")
REQUIRED_TAGS = ["tem4", "tem8", "bec", "gmat", "sat"]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def build(src=SRC, out_dir=OUT_DIR, min_total=10000):
    os.makedirs(out_dir, exist_ok=True)
    db = os.path.join(out_dir, "lexicon_extras.db")
    if not os.path.isfile(src):
        raise SystemExit("FAIL 找不到受限词表 CSV：%s（先跑 fetch_restricted_wordlists.py）" % src)
    if os.path.exists(db):
        os.remove(db)
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE restricted_entries(
            word TEXT NOT NULL, tag TEXT NOT NULL, source TEXT, license TEXT, risk TEXT, note TEXT,
            PRIMARY KEY(word, tag));
        CREATE INDEX idx_re_word ON restricted_entries(word);
        CREATE INDEX idx_re_tag ON restricted_entries(tag);
        CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
    """)
    rows, seen = [], set()
    with open(src, "r", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            w = (r.get("word") or "").strip().lower()
            t = (r.get("tag") or "").strip().lower()
            if not w or not t or (w, t) in seen:
                continue
            risk = (r.get("risk") or "").strip()
            if risk not in ("中", "高"):
                raise SystemExit("FAIL 非法 risk=%r（只允许 中/高）" % risk)
            seen.add((w, t))
            rows.append((w, t, (r.get("source") or "").strip(), (r.get("license") or "").strip(),
                         risk, (r.get("note") or "").strip()))
    con.executemany("INSERT INTO restricted_entries VALUES (?,?,?,?,?,?)", rows)
    counts = {t: 0 for t in REQUIRED_TAGS}
    for r in rows:
        if r[1] in counts:
            counts[r[1]] += 1
    con.executemany("INSERT INTO meta VALUES (?,?)", [
        ("pack_id", "restricted-words"), ("consent_required", "true"),
        ("redistribution", "user_risk"), ("risk_level", "high"),
        ("entries", str(len(rows))), ("tag_counts", json.dumps(counts, ensure_ascii=False)),
        ("built_at", time.strftime("%Y-%m-%dT%H:%M:%S")),
        ("warning", "词表来源为抓取/来源不明，仓库许可不覆盖数据；仅限用户明确授权后下载使用，不得默认分发"),
    ])
    con.commit()
    con.close()
    fail = []
    for t in REQUIRED_TAGS:
        if counts[t] < 100:
            fail.append("%s<100(%d)" % (t, counts[t]))
    if len(rows) < min_total and src == SRC:
        fail.append("total<=10000")
    man = {
        "manifest_version": 1,
        "entries": [{
            "id": "restricted-words",
            "kind": "dict-data",
            "version": "v1-local",
            "license": "LicenseRef-ScrapedWordlists",
            "commercial_ok": False,
            "consent_required": True,
            "risk_level": "high",
            "redistribution_note": "数据抓取自商业 App/网站或上游无许可；本仓库仅作个人/研究用途分发，用户须自行承担风险",
            "source_url": "local:work/external_restricted",
            "path": "restricted/lexicon_extras.db",
            "size_bytes": os.path.getsize(db),
            "sha256": sha256(db),
            "release_tag": "v1-local",
            "optional": True,
            "tag_counts": counts,
            "entries": len(rows),
            "note": "不进 APK；App 需弹风险确认，用户勾选后才从 Releases 下载",
        }],
    }
    with open(os.path.join(out_dir, "restricted-manifest.json"), "w", encoding="utf-8") as f:
        json.dump(man, f, ensure_ascii=False, indent=2)
    print(json.dumps({"entries": len(rows), "tag_counts": counts, "db_bytes": os.path.getsize(db),
                      "db_sha256": man["entries"][0]["sha256"]}, ensure_ascii=False, indent=2))
    if fail:
        raise SystemExit("FAIL 判据: " + "; ".join(fail))
    print("OK 受限词表大库构建完成（仅本地 work/data/lexicon_extras.db）")
    return 0


def self_test():
    ok = fail = 0

    def chk(n, c):
        nonlocal ok, fail
        print(("PASS " if c else "FAIL ") + n)
        ok, fail = (ok + 1, fail) if c else (ok, fail + 1)

    tmp = tempfile.mkdtemp(prefix="od-extras-")
    src = os.path.join(tmp, "restricted.csv")
    with open(src, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["word", "tag", "source", "license", "risk", "note"])
        for i in range(150):
            for t in REQUIRED_TAGS:
                w.writerow(("word%d_%s" % (i, t), t, "src", "none", "高", "test"))
        w.writerow(("dup", "tem4", "src", "none", "高", "x"))
        w.writerow(("dup", "tem4", "src2", "none", "高", "x"))
    try:
        build(src, os.path.join(tmp, "out"), min_total=1)
        chk("构建成功", True)
        con = sqlite3.connect(os.path.join(tmp, "out", "lexicon_extras.db"))
        chk("去重生效", con.execute("SELECT COUNT(*) FROM restricted_entries WHERE word='dup'").fetchone()[0] == 1)
        chk("每 tag 150（+1 个去重用例）", con.execute("SELECT COUNT(*) FROM restricted_entries WHERE tag='tem4'").fetchone()[0] == 151)
        con.close()
        man = json.load(open(os.path.join(tmp, "out", "restricted-manifest.json"), encoding="utf-8"))
        e = man["entries"][0]
        chk("manifest 含 consent_required/risk", e["consent_required"] is True and e["risk_level"] == "high")
        bad = os.path.join(tmp, "bad.csv")
        with open(bad, "w", encoding="utf-8") as f:
            f.write("word,tag,source,license,risk,note\nx,tem4,s,l,低,n\n")
        try:
            build(bad, os.path.join(tmp, "badout"))
            chk("非法 risk 被拒", False)
        except SystemExit:
            chk("非法 risk 被拒", True)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n自检结果：%d 项通过，%d 项失败" % (ok, fail))
    return 0 if fail == 0 else 1


def main():
    ap = argparse.ArgumentParser(description="构建受限词表大库（仅本地，不入 APK）")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        sys.exit(self_test())
    if not args.build:
        ap.print_help()
        return 2
    sys.exit(build())


if __name__ == "__main__":
    main()
