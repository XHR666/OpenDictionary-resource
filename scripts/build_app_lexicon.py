#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_app_lexicon.py — 从完整词典库生成 App 内置的紧凑词典（SQLite）。

输入：完整库（含 entries/word_tags/lemmas/phrase_entries/wordbook_entries 等）
输出：可放在 Android assets 的 lexicon.db（只读），包含：
  entries(word, phonetic, translation, pos, tag, exchange, frq)
  word_tags(word, tag)
  lemmas(form, lemma, kind)
  phrases(phrase, translation, book_id, kind)
  wordbook_entries(book_id, word, rank)
  meta(key, value)
  entries_fts (FTS5: word, translation)

用法：python3 scripts/build_app_lexicon.py --source <full.db> --out <assets/lexicon.db> [--limit 150000]
"""
import argparse, os, sqlite3, sys, time


def build(source, out, limit=150000, max_phrases=80000):
    if not os.path.isfile(source):
        raise SystemExit(f"找不到完整库: {source}")
    if os.path.exists(out):
        os.remove(out)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    src = sqlite3.connect(source)
    src.row_factory = sqlite3.Row
    dst = sqlite3.connect(out)
    dst.executescript("""
        PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
        CREATE TABLE entries(word TEXT PRIMARY KEY, phonetic TEXT, translation TEXT, definition TEXT, pos TEXT, tag TEXT, exchange TEXT, frq INTEGER DEFAULT 0);
        CREATE TABLE word_tags(word TEXT, tag TEXT);
        CREATE INDEX idx_word_tags_word ON word_tags(word);
        CREATE TABLE lemmas(form TEXT PRIMARY KEY, lemma TEXT, kind TEXT);
        CREATE INDEX idx_lemmas_lemma ON lemmas(lemma);
        CREATE TABLE phrases(phrase TEXT, translation TEXT, book_id TEXT, kind TEXT, source TEXT, license TEXT);
        CREATE INDEX idx_phrases_first ON phrases(substr(phrase,1,24));
        CREATE TABLE wordbook_entries(book_id TEXT, word TEXT, rank INTEGER);
        CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
    """)
    # 选词：有考试标签，或词频排名靠前；按优先级截断
    base = src.execute("""SELECT word, phonetic, translation, definition, pos, tag, exchange, frq FROM entries
        WHERE (tag IS NOT NULL AND tag != '') OR CAST(frq AS INTEGER) > 0 OR CAST(bnc AS INTEGER) > 0
        ORDER BY (CASE WHEN tag != '' THEN 0 ELSE 1 END), CAST(frq AS INTEGER), word LIMIT ?""", (limit,)).fetchall()
    rows = list(base)
    known = set(r["word"].lower() for r in rows)
    if len(rows) < limit:
        fill = src.execute("""SELECT word, phonetic, translation, definition, pos, tag, exchange, frq FROM entries
            WHERE word GLOB '[a-z]*' AND instr(word,' ')=0 AND LENGTH(word) BETWEEN 2 AND 18 AND translation != ''
            ORDER BY LENGTH(word), word LIMIT ?""", (limit * 2,)).fetchall()
        for r in fill:
            k = r["word"].lower()
            if k in known: continue
            known.add(k); rows.append(r)
            if len(rows) >= limit: break
    print(f"entries selected: {len(rows)}")
    dst.executemany("INSERT OR REPLACE INTO entries VALUES (?,?,?,?,?,?,?,?)",
                    [(r["word"], r["phonetic"] or "", (r["translation"] or "").replace("\\n", "\n"), (r["definition"] or "").replace("\\n", "\n"), r["pos"] or "", r["tag"] or "", r["exchange"] or "", r["frq"] or 0) for r in rows])
    tags = []
    for r in rows:
        for t in (r["tag"] or "").split():
            tags.append((r["word"], t))
    dst.executemany("INSERT INTO word_tags VALUES (?,?)", tags)

    # 熟词生义：项目自编整理（释义/例句自写，不伪造考试来源）
    dst.execute("CREATE TABLE sense(word TEXT, pos TEXT, meaning TEXT, example TEXT, source TEXT)")
    senses = [
        ("weather","v.","经受住；平安度过（困境）","The company weathered the storm and kept all its employees.","常见高考/CET 语境 · 自编例句"),
        ("run","v.","经营；管理","She runs a small bookshop in the old town.","常见高考/CET 语境 · 自编例句"),
        ("book","v.","预订","We booked a table for two at seven.","常见高考/CET 语境 · 自编例句"),
        ("address","v.","处理；设法解决","The report addresses the problem of food waste.","常见高考/CET 语境 · 自编例句"),
        ("company","n.","陪伴；同伴","I enjoy the company of old friends.","常见高考/CET 语境 · 自编例句"),
        ("matter","v.","要紧；有关系","It does not matter if you are a little late.","常见高考/CET 语境 · 自编例句"),
        ("spring","v.","突然出现；涌现","Tears sprang to her eyes.","常见高考/CET 语境 · 自编例句"),
        ("bank","v.","指望；依赖（bank on）","You can bank on him to keep his word.","常见高考/CET 语境 · 自编例句"),
        ("right","n.","权利","Everyone has the right to a fair trial.","常见高考/CET 语境 · 自编例句"),
        ("fine","n./v.","罚款","He was fined for parking in the wrong place.","常见高考/CET 语境 · 自编例句"),
        ("mean","adj.","吝啬的；刻薄的","It was mean of him to laugh at her mistake.","常见高考/CET 语境 · 自编例句"),
        ("order","n.","秩序；命令","The teacher asked for order in the classroom.","常见高考/CET 语境 · 自编例句"),
        ("present","v.","呈现；颁发","She presented her research to the class.","常见高考/CET 语境 · 自编例句"),
        ("train","v.","训练；培养","The team trained hard for the match.","常见高考/CET 语境 · 自编例句"),
        ("plant","v.","安放；栽种","He planted himself in the front row.","常见高考/CET 语境 · 自编例句"),
        ("stand","v.","忍受","I cannot stand the noise any longer.","常见高考/CET 语境 · 自编例句"),
        ("gooner","n.","阿森纳球迷；亦可能为成人网络俚语（需语境判断）","In football talk, a Gooner supports Arsenal.","网络/足球语境 · 语域提示"),
    ]
    dst.executemany("INSERT INTO sense VALUES (?,?,?,?,?)", senses)
    print(f"senses: {len(senses)}")

    # 常用中文→英文候选（自编映射，离线语义反查兜底）
    dst.execute("CREATE TABLE zh_alias(zh TEXT PRIMARY KEY, words TEXT)")
    aliases = {
        "东西": "thing,something,stuff,object", "风评": "reputation,public opinion", "天气": "weather",
        "平安度过": "weather,get through,survive", "老师": "teacher", "学生": "student", "钱": "money",
        "厕所": "toilet,restroom", "照片": "photo,picture", "电脑": "computer", "手机": "phone",
        "医院": "hospital", "工作": "work,job", "学习": "study,learn", "吃饭": "eat", "睡觉": "sleep",
        "漂亮": "beautiful,pretty", "高兴": "happy,glad", "生气": "angry", "害怕": "afraid,scared",
        "重要": "important", "困难": "difficult,hard", "帮助": "help", "朋友": "friend", "家": "home,family",
        "时间": "time", "地方": "place", "事情": "thing,matter", "问题": "problem,question", "方法": "method,way",
        "世界": "world", "国家": "country", "城市": "city", "学校": "school", "书": "book", "水": "water",
        "火": "fire", "食物": "food", "语言": "language", "音乐": "music", "电影": "movie,film", "游戏": "game",
        "颜色": "color", "数字": "number", "健康": "health", "医生": "doctor", "警察": "police", "律师": "lawyer",
        "工程师": "engineer", "苹果": "apple", "香蕉": "banana", "猫": "cat", "狗": "dog", "爱": "love",
        "恨": "hate", "希望": "hope,wish", "梦想": "dream", "成功": "success", "失败": "failure",
        "错误": "mistake,error", "正确": "correct,right", "开始": "start,begin", "结束": "end,finish",
        "快": "fast,quick", "慢": "slow", "大": "big,large", "小": "small,little", "多": "many,much",
        "少": "few,little", "好": "good,well", "坏": "bad", "新": "new", "旧": "old", "冷": "cold", "热": "hot",
    }
    dst.executemany("INSERT OR REPLACE INTO zh_alias VALUES (?,?)", list(aliases.items()))
    print(f"zh_alias: {len(aliases)}")

    # 由中文释义相似度生成"同近义"候选（仅作参考，标注来源算法）
    dst.execute("CREATE TABLE related(word TEXT, related_word TEXT, relation TEXT)")
    dst.execute("CREATE INDEX idx_related_word ON related(word)")
    import re
    from collections import defaultdict
    first_gloss = {}
    for r in rows:
        tr = (r["translation"] or "").replace("\\n", "\n").strip()
        if not tr: continue
        first = re.split(r"[；;\n]", tr)[0]
        first = re.sub(r"\[[^\]]*\]", "", first)
        first = re.sub(r"[^\u4e00-\u9fff]", "", first)
        if len(first) >= 2:
            first_gloss[r["word"]] = first[:8]
    groups = defaultdict(list)
    for w, gloss in first_gloss.items():
        groups[gloss[:4]].append(w)
    pairs = []
    for key, ws in groups.items():
        if len(ws) < 2 or len(ws) > 40: continue
        for w in ws:
            for other in ws:
                if w == other: pairs.append((w, other))
                if len(pairs) >= 150000: break
            if len(pairs) >= 150000: break
        if len(pairs) >= 150000: break
    rel_rows = [(w, o, "释义相近") for (w, o) in pairs]
    dst.executemany("INSERT INTO related VALUES (?,?,?)", rel_rows)
    print(f"related rows: {len(rel_rows)}")
    # lemmas：仅保留与选中词相关（form 或 lemma 在选中集）
    lemmas = src.execute("SELECT form, lemma, kind FROM lemmas").fetchall()
    keep_lemmas = [(l["form"], l["lemma"], l["kind"]) for l in lemmas
                   if (l["lemma"] or "").lower() in known or (l["form"] or "").lower() in known]
    dst.executemany("INSERT OR REPLACE INTO lemmas VALUES (?,?,?)", keep_lemmas)
    print(f"lemmas: {len(keep_lemmas)}")
    # 短语：优先高考/拉丁/专四专八，再补 ECDICT 多词（首词在选中集）
    pref = src.execute("SELECT phrase, translation, book_id, kind, source, license FROM phrase_entries WHERE book_id IN ('gk_phrases','latin_phrases','tem4_phrases','tem8_phrases')").fetchall()
    dst.executemany("INSERT OR IGNORE INTO phrases VALUES (?,?,?,?,?,?)",
                    [(r["phrase"], r["translation"] or "", r["book_id"], r["kind"] or "phrase", r["source"] or "", r["license"] or "") for r in pref])
    more = src.execute("SELECT phrase, translation, book_id, kind, source, license FROM phrase_entries WHERE book_id='phrases_ecdict' LIMIT ?", (max_phrases,)).fetchall()
    dst.executemany("INSERT OR IGNORE INTO phrases VALUES (?,?,?,?,?,?)",
                    [(r["phrase"], r["translation"] or "", r["book_id"], r["kind"] or "phrase", r["source"] or "", r["license"] or "") for r in more])
    print(f"phrases: {len(pref) + len(more)}")
    wb = src.execute("SELECT book_id, word, rank FROM wordbook_entries WHERE book_id='gk'").fetchall()
    dst.executemany("INSERT OR REPLACE INTO wordbook_entries VALUES (?,?,?)", [(r["book_id"], r["word"], r["rank"]) for r in wb])
    if not wb:
        gk = src.execute("SELECT word, rowid FROM gaokao ORDER BY rowid").fetchall()
        dst.executemany("INSERT OR REPLACE INTO wordbook_entries VALUES ('gk', ?, ?)", [(r["word"], r["rowid"]) for r in gk])
        print(f"gk entries from gaokao: {len(gk)}")
    dst.execute("CREATE VIRTUAL TABLE entries_fts USING fts5(word, translation, definition, content='entries', content_rowid='rowid')")
    dst.execute("INSERT INTO entries_fts(rowid, word, translation, definition) SELECT rowid, word, translation, definition FROM entries")
    dst.executemany("INSERT OR REPLACE INTO meta VALUES (?,?)", [
        ("schema", "app-lexicon-1"), ("source", os.path.basename(source)), ("built_at", time.strftime("%Y-%m-%dT%H:%M:%S")),
        ("entries", str(len(rows))), ("with_definition", str(sum(1 for r in rows if r["definition"]))),  ("lemmas", str(len(keep_lemmas))), ("phrases", str(len(pref) + len(more))),
    ])
    dst.commit()
    dst.execute("VACUUM")
    dst.commit()
    dst.close(); src.close()
    size = os.path.getsize(out)
    print(f"OK {out} {size} bytes")
    if size > 120 * 1024 * 1024:
        raise SystemExit("FAIL 体积超过 120MB")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=150000)
    args = ap.parse_args()
    build(args.source, args.out, args.limit)
