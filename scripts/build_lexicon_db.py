#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_lexicon_db.py — 从 ECDICT CSV 构建词典数据库（M1 数据管线）

产物（默认写到 work/data/，work/ 已被 .gitignore 排除，不提交）：
  1. lexicon_ecdict_full.db  内部全量库（开发/复核用；含 bnc/frq 等受限字段）
  2. lexicon_core.db         可分发包候选（只含可分发字段；bnc/frq/collins/oxford/detail/audio 不进）
  3. wordlists/gk.csv        高考词表（tag 含 gk；按内部词频排序，仅本地/内部参考）
  4. build-report.json       读数（行数/去重/tag 计数/sha256/耗时），用于 R6 改前改后对照

设计约束（决策 D11/D16/D21）：
  - 词表来源仅 ECDICT（MIT 代码；数据链待法务抽检）——本脚本不联网、不改源文件；
  - 分发库剔除受限语料派生字段（BNC/COCA 词频、柯林斯/牛津衍生评分、未知来源 detail/audio）；
  - 全部字段先进内部库，人工复核后再决定发布子集；
  - 判据必须能失败：坏列/空文件/重复词异常/计数不符一律非零退出；--self-test 内置正反用例。
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

FIELDS = ["word", "phonetic", "definition", "translation", "pos",
          "collins", "oxford", "tag", "bnc", "frq", "exchange", "detail", "audio"]
EXAM_TAGS = ["zk", "gk", "cet4", "cet6", "ky", "ielts", "toefl", "sat",
             "gre", "gmat", "bec", "tem4", "tem8"]
# 分发库排除字段（法律风险待法务确认；见 docs/proj/05 与索引 §4.6.1）
# 注意：排除的是"标注列"，不是单词本身——所有单词始终保留在 entries 里（D23）
NON_DISTRIBUTABLE = ["bnc", "frq", "collins", "oxford", "detail", "audio"]
# 仅"内部"可用的标注列（用户确认单词不能因这些标注被排除；标注本身暂不进发布包）
INTERNAL_ONLY_MARKS = ["collins", "oxford"]


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def norm_int(v):
    v = (v or "").strip()
    if not v:
        return None
    try:
        return int(float(v))
    except ValueError:
        return None


def split_tags(tag):
    return [t for t in (tag or "").replace(",", " ").split() if t]


def write_csv_rows(rows, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["word", "translation", "tag"])
        w.writerows(rows)


def build(csv_path, out_dir, limit=None, verbose=True, min_gaokao=1000, min_lemmas=10000, extra_tags=None, phrases=None):
    t0 = time.time()
    os.makedirs(out_dir, exist_ok=True)
    full_db = os.path.join(out_dir, "lexicon_ecdict_full.db")
    dist_db = os.path.join(out_dir, "lexicon_core.db")
    gk_csv = os.path.join(out_dir, "wordlists", "gk.csv")
    report_path = os.path.join(out_dir, "build-report.json")
    for p in (full_db, dist_db):
        if os.path.exists(p):
            os.remove(p)

    if not os.path.isfile(csv_path):
        raise SystemExit(f"FAIL 源文件不存在: {csv_path}")
    src_sha = sha256_file(csv_path)

    con_f = sqlite3.connect(full_db)
    con_d = sqlite3.connect(dist_db)
    for con in (con_f, con_d):
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=OFF")

    con_f.execute(f"CREATE TABLE entries ({', '.join(FIELDS)}, PRIMARY KEY(word))")
    con_f.execute("CREATE TABLE tags (word TEXT NOT NULL, tag TEXT NOT NULL)")
    con_f.execute("CREATE TABLE gaokao (word TEXT PRIMARY KEY, frq_rank INTEGER, bnc_rank INTEGER)")
    con_f.execute("CREATE TABLE wordbooks (book_id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT)")
    con_f.execute("CREATE TABLE wordbook_entries (book_id TEXT NOT NULL, word TEXT NOT NULL, rank INTEGER, PRIMARY KEY(book_id, word))")
    con_f.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")

    dist_fields = [f for f in FIELDS if f not in NON_DISTRIBUTABLE]
    con_d.execute(f"CREATE TABLE entries ({', '.join(dist_fields)}, PRIMARY KEY(word))")
    con_d.execute("CREATE TABLE word_tags (word TEXT NOT NULL, tag TEXT NOT NULL)")
    con_d.execute("CREATE TABLE wordbooks (book_id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT)")
    con_d.execute("CREATE TABLE wordbook_entries (book_id TEXT NOT NULL, word TEXT NOT NULL, rank INTEGER, PRIMARY KEY(book_id, word))")
    con_d.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    # 外部词表（补充标签）与短语表（D21 扩展）
    for con in (con_f, con_d):
        con.execute("CREATE TABLE IF NOT EXISTS tag_sources (word TEXT, tag TEXT, source TEXT, license TEXT, confidence TEXT)")
        con.execute("CREATE TABLE IF NOT EXISTS external_entries (word TEXT PRIMARY KEY, tag TEXT, source TEXT, license TEXT, confidence TEXT)")
        con.execute("CREATE TABLE IF NOT EXISTS phrase_entries (phrase TEXT, translation TEXT, book_id TEXT, source TEXT, license TEXT, kind TEXT DEFAULT 'phrase', PRIMARY KEY(book_id, phrase))")
    # FTS5 全文索引（word + translation）与词形还原表
    for con in (con_f, con_d):
        con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(word, translation, tokenize='unicode61')")
    con_f.execute("CREATE TABLE lemmas (form TEXT PRIMARY KEY, lemma TEXT NOT NULL, kind TEXT)")
    con_f.execute("CREATE INDEX idx_lemmas_lemma ON lemmas(lemma)")
    con_d.execute("CREATE TABLE lemmas (form TEXT PRIMARY KEY, lemma TEXT NOT NULL, kind TEXT)")
    con_d.execute("CREATE INDEX idx_lemmas_lemma ON lemmas(lemma)")

    tag_counts = {t: 0 for t in EXAM_TAGS}
    gk_rows = []
    seen = 0
    bad_rows = 0
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None or [x.strip() for x in reader.fieldnames] != FIELDS:
            raise SystemExit(f"FAIL CSV 列不符。期望 {FIELDS}，实际 {reader.fieldnames}")
        f_rows, d_rows, tag_rows = [], [], []
        for row in reader:
            if limit and seen >= limit:
                break
            seen += 1
            row = {k: (row.get(k) or "").strip() for k in FIELDS}
            word = row["word"]
            if not word or " " == word:
                bad_rows += 1
                continue
            f_rows.append(tuple(row[k] for k in FIELDS))
            d_rows.append(tuple(row[k] for k in dist_fields))
            tags = split_tags(row["tag"])
            for t in tags:
                if t in tag_counts:
                    tag_counts[t] += 1
                tag_rows.append((word, t))
            if "gk" in tags:
                gk_rows.append((word, norm_int(row["frq"]), norm_int(row["bnc"]), row["translation"], row["tag"]))
            if len(f_rows) >= 2000:
                con_f.executemany(f"INSERT OR IGNORE INTO entries VALUES ({','.join(['?'] * len(FIELDS))})", f_rows)
                con_d.executemany(f"INSERT OR IGNORE INTO entries VALUES ({','.join(['?'] * len(dist_fields))})", d_rows)
                con_f.executemany("INSERT INTO tags VALUES (?,?)", tag_rows)
                con_d.executemany("INSERT INTO word_tags VALUES (?,?)", tag_rows)
                con_f.executemany("INSERT INTO entries_fts(word,translation) VALUES (?,?)", [(r[0], r[3]) for r in f_rows])
                con_d.executemany("INSERT INTO entries_fts(word,translation) VALUES (?,?)", [(r[0], r[3]) for r in d_rows])
                lemma_rows = []
                for r in f_rows:
                    ex, w = r[FIELDS.index("exchange")], r[0]
                    for item in (ex or "").split("/"):
                        if ":" in item:
                            kind, val = item.split(":", 1)
                            if not val:
                                continue
                            # Exchange 语义：0:lemma 表示"本词的词元是 val"；其余表示"val 是本词的变形"
                            if kind == "0":
                                lemma_rows.append((w, val, "0"))
                            elif val != w:
                                lemma_rows.append((val, w, kind))
                if lemma_rows:
                    sql = ("INSERT INTO lemmas VALUES (?,?,?) ON CONFLICT(form) DO UPDATE SET lemma=excluded.lemma, kind=excluded.kind "
                           "WHERE excluded.kind='0' AND lemmas.kind!='0'")
                    con_f.executemany(sql, lemma_rows)
                    con_d.executemany(sql, lemma_rows)
                f_rows, d_rows, tag_rows = [], [], []
        if f_rows:
            con_f.executemany(f"INSERT OR IGNORE INTO entries VALUES ({','.join(['?'] * len(FIELDS))})", f_rows)
            con_d.executemany(f"INSERT OR IGNORE INTO entries VALUES ({','.join(['?'] * len(dist_fields))})", d_rows)
            con_f.executemany("INSERT INTO tags VALUES (?,?)", tag_rows)
            con_d.executemany("INSERT INTO word_tags VALUES (?,?)", tag_rows)
            con_f.executemany("INSERT INTO entries_fts(word,translation) VALUES (?,?)", [(r[0], r[3]) for r in f_rows])
            con_d.executemany("INSERT INTO entries_fts(word,translation) VALUES (?,?)", [(r[0], r[3]) for r in d_rows])
            lemma_rows = []
            for r in f_rows:
                ex, w = r[FIELDS.index("exchange")], r[0]
                for item in (ex or "").split("/"):
                    if ":" in item:
                        kind, val = item.split(":", 1)
                        if not val:
                            continue
                        if kind == "0":
                            lemma_rows.append((w, val, "0"))
                        elif val != w:
                            lemma_rows.append((val, w, kind))
            if lemma_rows:
                sql = ("INSERT INTO lemmas VALUES (?,?,?) ON CONFLICT(form) DO UPDATE SET lemma=excluded.lemma, kind=excluded.kind "
                       "WHERE excluded.kind='0' AND lemmas.kind!='0'")
                con_f.executemany(sql, lemma_rows)
                con_d.executemany(sql, lemma_rows)

    # ---- 合并外部补充词表（考试标签）与短语库 ----
    extra_report = {"tags_file": None, "tags_rows": 0, "external_words": 0, "phrases_file": None, "phrases_rows": 0}
    if extra_tags:
        if not os.path.isfile(extra_tags):
            raise SystemExit(f"FAIL 找不到 --extra-tags 文件: {extra_tags}")
        with open(extra_tags, "r", encoding="utf-8-sig", newline="") as f:
            rd = csv.DictReader(f)
            need = {"word", "tag", "source", "license", "confidence"}
            if not need.issubset(set(rd.fieldnames or [])):
                raise SystemExit(f"FAIL --extra-tags 列不全，需 {sorted(need)}，实际 {rd.fieldnames}")
            ext = []
            for row in rd:
                w = (row.get("word") or "").strip()
                t = (row.get("tag") or "").strip().lower()
                if not w or not t:
                    continue
                ext.append((w, t, (row.get("source") or "").strip(), (row.get("license") or "").strip(),
                            (row.get("confidence") or "").strip()))
        for con in (con_f, con_d):
            con.executemany("INSERT INTO tag_sources VALUES (?,?,?,?,?)", ext)
        con_f.executemany("INSERT INTO tags VALUES (?,?)", [(w, t) for w, t, *_ in ext])
        con_d.executemany("INSERT INTO word_tags VALUES (?,?)", [(w, t) for w, t, *_ in ext])
        known = {r[0] for r in con_d.execute("SELECT word FROM entries").fetchall()}
        ext_unknown = [r for r in ext if r[0] not in known]
        for con in (con_f, con_d):
            con.executemany("INSERT OR IGNORE INTO external_entries VALUES (?,?,?,?,?)", ext_unknown)
        extra_report.update(tags_file=os.path.basename(extra_tags), tags_rows=len(ext), external_words=len(ext_unknown))
        for w, t, *_ in ext:
            tag_counts[t] = tag_counts.get(t, 0) + 1
    if phrases:
        if not os.path.isfile(phrases):
            raise SystemExit(f"FAIL 找不到 --phrases 文件: {phrases}")
        with open(phrases, "r", encoding="utf-8-sig", newline="") as f:
            rd = csv.DictReader(f)
            need = {"phrase", "book_id", "source", "license"}
            if not need.issubset(set(rd.fieldnames or [])):
                raise SystemExit(f"FAIL --phrases 列不全，需 {sorted(need)}，实际 {rd.fieldnames}")
            ph = []
            for row in rd:
                phrase = (row.get("phrase") or "").strip()
                if not phrase:
                    continue
                ph.append((phrase, (row.get("translation") or "").strip(), (row.get("book_id") or "gk_phrases").strip(),
                           (row.get("source") or "").strip(), (row.get("license") or "").strip(),
                           (row.get("kind") or "phrase").strip()))
        books = {}
        for phrase, tr, bid, src, lic, kind in ph:
            books[bid] = books.get(bid, 0) + 1
        for bid, n in books.items():
            for con in (con_f, con_d):
                con.execute("INSERT OR REPLACE INTO wordbooks VALUES (?,?,?)", (bid, bid, f"外部短语库 {bid}（{n} 条）"))
        for con in (con_f, con_d):
            con.executemany("INSERT OR IGNORE INTO phrase_entries(phrase,translation,book_id,source,license,kind) VALUES (?,?,?,?,?,?)", ph)
        ranks, rows = {}, []
        for phrase, tr, bid, src, lic, kind in sorted(ph, key=lambda x: (x[2], x[0].lower())):
            ranks[bid] = ranks.get(bid, 0) + 1
            rows.append((bid, phrase, ranks[bid]))
        for con in (con_f, con_d):
            con.executemany("INSERT OR IGNORE INTO wordbook_entries VALUES (?,?,?)", rows)
        extra_report.update(phrases_file=os.path.basename(phrases), phrases_rows=len(ph))

    # 高考词表：内部按 frq 排名（缺失排最后），分发库按字母序（不携带受限词频）
    gk_sorted = sorted(gk_rows, key=lambda r: (r[1] is None, r[1] or 0, r[0].lower()))
    con_f.executemany("INSERT INTO gaokao VALUES (?,?,?)", [(w, frq, bnc) for w, frq, bnc, _t, _g in gk_sorted])
    con_d.execute("INSERT INTO wordbooks VALUES ('gk','高考','ECDICT tag 含 gk 的词条（分发库按字母序）')")
    con_d.executemany("INSERT OR IGNORE INTO wordbook_entries VALUES ('gk',?,?)",
                      [(w, i + 1) for i, (w, *_rest) in enumerate(sorted(gk_rows, key=lambda r: r[0].lower()))])
    write_csv_rows([(w, tr, tg) for w, _frq, _bnc, tr, tg in gk_sorted], gk_csv)

    # meta / 索引
    for con, meta in ((con_f, {"contains": "all", "source": "ECDICT ecdict.csv", "license": "MIT (code); data chain pending"}),
                      (con_d, {"contains": "distributable", "excluded_fields": ",".join(NON_DISTRIBUTABLE),
                               "source": "ECDICT ecdict.csv", "license": "MIT (code); data chain pending"})):
        con.executemany("INSERT OR REPLACE INTO meta VALUES (?,?)", list(meta.items()) + [
            ("source_sha256", src_sha), ("source_rows", str(seen)),
            ("built_at", time.strftime("%Y-%m-%dT%H:%M:%S")), ("schema_version", "1.0.0"),
            ("tag_counts", json.dumps(tag_counts, ensure_ascii=False)), ("gaokao_count", str(len(gk_rows))),
        ])
        con.execute("CREATE INDEX idx_entries_word_lower ON entries(word)")
        con.execute("CREATE INDEX idx_tags_tag ON tags(tag)" if con is con_f else "CREATE INDEX idx_wt_tag ON word_tags(tag)")
        con.commit()

    counts = {
        "full_entries": con_f.execute("SELECT COUNT(*) FROM entries").fetchone()[0],
        "dist_entries": con_d.execute("SELECT COUNT(*) FROM entries").fetchone()[0],
        "tags_rows": con_f.execute("SELECT COUNT(*) FROM tags").fetchone()[0],
        "fts_rows": con_d.execute("SELECT COUNT(*) FROM entries_fts").fetchone()[0],
        "lemmas_rows": con_d.execute("SELECT COUNT(*) FROM lemmas").fetchone()[0],
        "gaokao_count": len(gk_rows),
        "external_tags": extra_report,
        "source_rows": seen,
        "bad_rows": bad_rows,
        "tag_counts": tag_counts,
        "excluded_fields": NON_DISTRIBUTABLE,
        "source_sha256": src_sha,
        "full_db_sha256": None,
        "dist_db_sha256": None,
        "sizes": {},
    }
    for con in (con_f, con_d):
        con.close()
    counts["full_db_sha256"] = sha256_file(full_db)
    counts["dist_db_sha256"] = sha256_file(dist_db)
    for p in (full_db, dist_db, gk_csv):
        counts["sizes"][os.path.basename(p)] = os.path.getsize(p)
    counts["duration_s"] = round(time.time() - t0, 2)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(counts, f, ensure_ascii=False, indent=2)

    # 判据（失败即非零退出）
    fail = []
    if counts["full_entries"] < 1:
        fail.append("full_entries=0")
    if counts["gaokao_count"] < min_gaokao and not limit:
        fail.append(f"gaokao_count 异常低: {counts['gaokao_count']}")
    if bad_rows:
        fail.append(f"bad_rows={bad_rows}")
    if counts["fts_rows"] < counts["dist_entries"] * 0.99:
        fail.append(f"FTS 行数异常: {counts['fts_rows']} vs {counts['dist_entries']}")
    if extra_tags and counts["external_tags"]["tags_rows"] == 0:
        fail.append("extra_tags 文件无有效行")
    if phrases and counts["external_tags"]["phrases_rows"] == 0:
        fail.append("phrases 文件无有效行")
    if counts["lemmas_rows"] < min_lemmas and not limit:
        fail.append(f"lemma 行数异常低: {counts['lemmas_rows']}")
    if counts["dist_entries"] != counts["full_entries"]:
        fail.append("dist_entries != full_entries（去重后应一致）")
    dist_cols = [r[1] for r in con_d_cols(dist_db)]
    if set(dist_cols) & set(NON_DISTRIBUTABLE):
        fail.append(f"分发库泄漏受限字段: {set(dist_cols) & set(NON_DISTRIBUTABLE)}")
    if verbose:
        print(json.dumps(counts, ensure_ascii=False, indent=2))
    if fail:
        raise SystemExit("FAIL 判据: " + "; ".join(fail))
    return counts


def con_d_cols(db):
    con = sqlite3.connect(db)
    cols = con.execute("PRAGMA table_info(entries)").fetchall()
    con.close()
    return cols


def self_test():
    """内置正反用例：小样本 → 表/计数/排除字段/高考词表/幂等；坏输入必须非零。"""
    ok = 0
    fail = 0
    tmp = tempfile.mkdtemp(prefix="lexdb-selftest-")
    csv_path = os.path.join(tmp, "mini.csv")
    rows = [
        ["run", "rʌn", "move fast\noperate", "跑；经营；运行", "v/n", "3", "1", "zk gk cet4", "100", "50", "p:ran/d:run", "", ""],
        ["schedule", "ˈʃedjuːl", "plan", "计划；时间表", "n/v", "2", "1", "gk cet4 cet6", "300", "200", "", "", ""],
        ["duplicate", "ˈdjuːplɪkeɪt", "copy", "复制；副本", "v/n/adj", "1", "", "cet6 ky", "900", "800", "", "", ""],
        ["风评", "", "", "reputation", "", "", "", "", "", "", "", "", ""],
    ]
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(FIELDS)
        w.writerows(rows)
    try:
        out = os.path.join(tmp, "out")
        c1 = build(csv_path, out, verbose=False, min_gaokao=1, min_lemmas=1)
        checks = [
            ("总行数=4", c1["full_entries"] == 4),
            ("高考>=2", c1["gaokao_count"] == 2),
            ("tag zk/gk/cet4 计数", c1["tag_counts"]["gk"] == 2 and c1["tag_counts"]["cet4"] == 2),
            ("分发库行数=4", c1["dist_entries"] == 4),
            ("受限字段不进分发库", not (set(r[1] for r in con_d_cols(os.path.join(out, "lexicon_core.db"))) & set(NON_DISTRIBUTABLE))),
            ("高考 CSV 存在且有序", os.path.isfile(os.path.join(out, "wordlists", "gk.csv"))),
            ("FTS+lemma 已建", c1["fts_rows"] == 4 and c1["lemmas_rows"] >= 1),
            ("幂等：同输入 full_db 哈希一致", (build(csv_path, out, verbose=False, min_gaokao=1, min_lemmas=1)["full_db_sha256"] == c1["full_db_sha256"])),
        ]
        for name, passed in checks:
            if passed:
                ok += 1
                print(f"PASS {name}")
            else:
                fail += 1
                print(f"FAIL {name}")
        # 反例：坏列必须非零退出
        bad = os.path.join(tmp, "bad.csv")
        with open(bad, "w", encoding="utf-8", newline="") as f:
            f.write("word,phonetic\nrun,rʌn\n")
        try:
            build(bad, os.path.join(tmp, "badout"), verbose=False)
            print("FAIL 坏列未被拒绝")
            fail += 1
        except SystemExit:
            print("PASS 坏列被拒绝（非零退出）")
            ok += 1
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n自检结果：{ok} 项通过，{fail} 项失败")
    return 0 if fail == 0 else 1


def main():
    ap = argparse.ArgumentParser(description="从 ECDICT CSV 构建词典数据库（内部全量 + 可分发包候选）")
    ap.add_argument("--csv", default="work/ECDICT/ecdict.csv", help="ECDICT CSV 路径")
    ap.add_argument("--out-dir", default="work/data", help="输出目录（默认 work/data，不入 git）")
    ap.add_argument("--limit", type=int, default=None, help="仅处理前 N 行（调试用）")
    ap.add_argument("--extra-tags", default=None, help="补充标签 CSV：word,tag,source,license,confidence")
    ap.add_argument("--phrases", default=None, help="短语 CSV：phrase,translation,book_id,source,license")
    ap.add_argument("--self-test", action="store_true", help="运行内置自检（不读写真实数据）")
    args = ap.parse_args()
    if args.self_test:
        sys.exit(self_test())
    counts = build(args.csv, args.out_dir, extra_tags=args.extra_tags, phrases=args.phrases)
    print(f"OK 构建完成：full={counts['full_entries']} dist={counts['dist_entries']} gk={counts['gaokao_count']}")


if __name__ == "__main__":
    main()
