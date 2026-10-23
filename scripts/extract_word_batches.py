#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""extract_word_batches.py — 切分开放词典词条，生成「AI 词条补全批次」文档（仅标准库，不联网）。

用法：python3 extract_word_batches.py [--input ecdict.csv] [--wordlist 词表] [--tags cet4,cet6]
      [--max-freq 20000] [--min-len 1] [--max-len 40] [--mode any|word|phrase] [--max-words 60]
      [--max-est-tokens 288000] [--tokens-per-word 3500] [--seed N] [--out batches] [--self-test]
字段表须与《03-AI词条补全规范》§3.2 一致、任务头须与 §4 一致：改字段要同时改三处
（规范表 / 本文件 FIELDS / 03a 示例批次）。不写死绝对路径，默认只读写当前目录。
"""
import argparse
import csv
import datetime
import json
import os
import random
import sys

VERSION, SCHEMA = "1.0.0", "entry-schema/1.0.0"
TAGS = ("zk", "gk", "cet4", "cet6", "ky", "ielts", "toefl", "sat", "gre", "gmat", "bec", "tem4", "tem8")
DOMAINS = ("economics", "computer_science", "transportation", "medicine", "law", "finance", "linguistics",
           "physics", "chemistry", "biology", "psychology", "management", "education", "military",
           "agriculture", "art", "environment", "electronics", "mechanical", "civil")
REGISTERS = ("formal", "neutral", "informal", "slang", "vulgar", "archaic", "literary", "technical", "regional", "humorous")
OUTPUT_LIMIT, USABLE_RATIO, HEADER_TOKENS, TPW = 384000, 0.75, 2500, 3500  # 输出上限/可用余量/头开销/每词 token

FIELDS = [  # 22 个顶层字段，(字段, 类型, 必填, 说明)；顺序即规范 §3.2 表格顺序
    ("entry_id", "string", "必填", "稳定 ID：`w-run` / `p-take-into-account`"), ("headword", "string", "必填", "词条原文"),
    ("headword_norm", "string", "必填", "小写归一，去重键"), ("entry_type", "enum", "必填", "`word` / `phrase` / `abbrev`"),
    ("syllables", "array[string]", "可选", "音节切分（F080）"), ("stress_pattern", "string|null", "可选", "主次重音/音变"),
    ("pronunciations", "array", "必填", "1–4 项，英美各 1"), ("pos_groups", "array", "必填", "≥1 组，组内含 `senses[]`"),
    ("domain_senses", "array", "可选", "≤6 条专业领域释义"), ("slang", "array", "可选", "俚语/非正式/粗俗/过时"),
    ("phrases", "array", "可选", "词组、习语、搭配（F072）"), ("relations", "object", "必填", "同反义/派生/易混（F070/F085）"),
    ("exam_tags", "array[enum]", "必填", "13 值枚举（F078），无则 `[]`"), ("cefr", "enum|null", "必填", "`A1`–`C2`，查不到 null"),
    ("register", "enum", "必填", "整体语域（10 值）"), ("frequency", "object", "必填", "`{bnc_rank,frq_rank,source,redistributable}`"),
    ("etymology", "object|null", "可选", "`{origin_language,root,narrative_zh,source_refs}`"), ("encyclopedia", "array", "必填", "维基 + 百度百科各 1"),
    ("source_refs", "array", "必填", "≥1；`{url,title,kind,retrieved_at,license}`"), ("uncertainties", "array", "必填", "可为 `[]`；`{field,reason}`"),
    ("self_check", "object", "必填", "`{links_checked,uncertain_count,no_fabrication_ack}`"), ("review", "object|null", "可选", "人工复核状态，AI 写 null"),
]

# 固定任务头：@@XXX@@ 为占位符；与规范 §4 逐字对应（改这里必须同步改规范）
TPL = """# AI 词条补全批次 · @@BID@@

> **整份转发即可**：本文件自包含（任务 / 规则 / 字段 / 词表），接收方不需要其他文件。
> 只输出**一个 JSON 对象**；不要前言、不要结语、不要 json 围栏以外的文字。
> 规范：@@SCHEMA@@ · 母本 `docs/proj/03-AI词条补全规范.md` v@@VERSION@@

## 0. 元信息
- 批次号 `@@BID@@` · 词条数 @@N@@（单词 @@NW@@ / 短语 @@NP@@）· 词表来源 @@SOURCE@@
- 估算 ≈ @@EST@@ token（@@N@@ × @@TPW@@ + 任务头 @@HDR@@）/ 硬上限 @@LIMIT@@（占 @@RATIO@@%，余量 ≥ @@MARGIN@@%）
- 规范 @@SCHEMA@@（22 个顶层字段 / 15 必填）· 生成器 `extract_word_batches.py` @@VERSION@@ · @@NOW@@
- 许可：数据源结论以《唯一索引》**Ch4 §4.6.1** 为准（见 R9）；回传先过 §5，再过《规范》§6 的 V01–V12
## 1. 任务
- **1.1 角色**：你是英语词典编纂员兼语料核实员，为中文母语学习者补全词条，输出可直接入库的结构化数据。
- **1.2 输入**：§6 词表共 @@N@@ 条；条目顺序 = 输出顺序，不得增删、改写或合并词目。
- **1.3 输出**：一个 JSON 对象，顶层键**仅** `schema` / `batch_id` / `generated_at` / `entries` / `batch_notes`；`entries` 长度必须等于 @@N@@。
- **1.4 深度与语言**：每条 2,500–4,000 token（中英混排）；"极其全面"优先于"简洁"；解释性字段用简体中文，英文例句保留原文并给中文翻译。
- **1.5 边界**：只做词条本身，不做语法讲解、不做学习计划、不引用其他词条内容（`relations` 提到他词不受此限）。
## 2. 查询规则（检索优先，R1–R9）
- **R1 先检索，再回答**：每个词条先检索再写字段，不得凭记忆直出。
- **R2 一手优先**：Wiktionary（英/中）、Wikipedia、百度百科、考试大纲或官方词表、专业学会术语表；论坛与自媒体只作线索。
- **R3 链接必须真实**：`source_refs[].url`、`encyclopedia[].url` 必须是本次真实打开过的页面；拼凑、猜测、路径写错一律禁止。
- **R4 无法核实 → `null` + 原因**：写进 `uncertainties[]`（`{"field":"…","reason":"…"}`）；禁止编造，`reason` 不得只写"不确定"。
- **R5 考试标签只认大纲**：13 个枚举见 §4.4；大纲未收录即不入该标签，宁可 `[]`。
- **R6 音标**：英/美各一条 IPA，用 `variant` 区分；不确定的美式变体写 null 并计入 uncertainties。
- **R7 专业释义**：只有词典或术语表明确标注学科时才填 `domain_senses`，否则 `[]`。
- **R8 俚语与非正式**：`register` 必须标（slang/informal/vulgar/dated），并给地区与使用警示。
- **R9 许可边界（Ch4 §4.6.1）**：Wiktionary/Wikipedia 为 CC BY-SA（署名 + 同许可 + 标注修改）；DANTE 为 CC BY 4.0；百度百科许可未核实 → 只给链接、不摘正文；ECDICT 的 MIT 仅覆盖代码、BNC 频次禁止再分发语料，故 `frequency.redistributable` 默认 `false`。
## 3. 禁止事项（X1–X6）
- **X1** 禁止编造 URL、书名、页码、例句出处、索引号。
- **X2** 禁止引用已判不可商用的源：COCA、Datamuse、Merriam-Webster/Collins/Oxford API、OpenSubtitles、有道/百度翻译 API、Quotable 文本、CLEC、ProPOSEL、UniversalCEFR。
- **X3** 禁止大段摘抄维基/百度百科正文：只给链接，摘要自写且 ≤120 字。
- **X4** 禁止由中文释义反推词频、CEFR、考试标签；这些字段必须有可查来源或写 null。
- **X5** 禁止输出 JSON 以外内容；禁止省略字段；禁止用省略号占位。
- **X6** 禁止用"可能/大概"包装不确定项；不确定就走 R4。

## 4. 输出格式（@@SCHEMA@@）
**4.1 顶层骨架**：`{"schema":"@@SCHEMA@@","batch_id":"@@BID@@","generated_at":"<ISO-8601 UTC>","entries":[ … 22 字段见 4.2 … ],"batch_notes":"≤200 字取舍与覆盖缺口"}`

**4.2 条目字段（22 个顶层字段）**

@@FIELDS@@

**4.3 嵌套结构**（逐项写全，不得缺键）：`pronunciations[]`=`{variant, ipa, arpabet, note}` · `pos_groups[]`=`{pos, senses[]}` · `senses[]`=`{sense_no, def_zh, def_en, register, cefr, domain, examples[]}` · `examples[]`=`{en, zh, source_url, source_kind}` · `domain_senses[]`=`{domain, def_zh, def_en, example_en, example_zh, source_refs[]}` · `slang[]`=`{register, def_zh, def_en, region, example_en, warning, source_refs[]}` · `phrases[]`=`{text, phrase_type, def_zh, example_en, register, source_refs[]}` · `relations`=`{synonyms, antonyms, hypernyms, hyponyms, derived, confusables[]}` · `confusables[]`=`{word, distinction_zh, source_refs[]}` · `source_refs[]`=`{url, title, kind, retrieved_at, license}`

**4.4 枚举（拼写必须完全一致）**
- `exam_tags`（13）：zk 初中 · gk 高中 · cet4 · cet6 · ky 考研 · ielts · toefl · sat · gre · gmat · bec 商务英语 · tem4 专四 · tem8 专八
- `domain`（20）：economics 经济学 · computer_science 计算机科学技术 · transportation 交通运输工程 · medicine 医学 · law 法学 · finance 金融学 · linguistics 语言学 · physics 物理学 · chemistry 化学 · biology 生物学 · psychology 心理学 · management 管理学 · education 教育学 · military 军事学 · agriculture 农学 · art 艺术学 · environment 环境科学 · electronics 电子与通信 · mechanical 机械工程 · civil 土木工程
- `register`（10）：formal · neutral · informal · slang · vulgar · archaic · literary · technical · regional · humorous
- 其他：`cefr`=A1 A2 B1 B2 C1 C2 或 null；`pos`=n. v. adj. adv. prep. conj. pron. det. num. art. interj. aux. phr. abbr.；`phrase_type`=idiom phrasal_verb collocation compound proverb；`source_kind`=dictionary encyclopedia corpus etymology syllabus usage_note；`license`=PD CC0-1.0 CC-BY-4.0 CC-BY-SA-4.0 MIT Apache-2.0 GFDL project-internal unverified
- **4.5 取值约定**：`null` = 查过但查不到（必须同步写入 `uncertainties[]`）；`[]` = 该词确实没有此项；空串 `""` 禁用。
## 5. 自检清单（输出前逐条确认，结果回填 `self_check`）
- **C1** 条目数 = 词表条数，顺序一致，`headword_norm` 无重复。
- **C2** 每个 URL 真实可达；`encyclopedia` 含 `wikipedia_en` 与 `baike_baidu` 各一条。
- **C3** 15 个必填字段齐全；每个 `null` 都能在 `uncertainties[]` 找到对应原因。
- **C4** 枚举拼写与 §4.4 完全一致，`exam_tags` 无自造标签。
- **C5** `self_check` 三个数值与实际一致，`no_fabrication_ack` 必须为 true。
- **C6** JSON 可被机器直接解析：无注释、无尾逗号、无单引号、无省略号。

## 6. 词表（@@N@@ 条，顺序 = 输出顺序）
@@WORDS@@

> 音标 / 标签 / frq 由管线从 ECDICT 预填，本批为 @@MODE@@ 模式，空值显示 `-`；预填值仅供参考，以你的检索结果为准。
## 7. 预算与交付
- **7.1 预算**：本批 ≈ @@EST@@ token / @@LIMIT@@；超过 @@USABLE@@（75%）即视为异常，先压缩 `phrases` / `etymology` 叙述文字，不得删字段。
- **7.2 分片**：确需分片时每片自带 `batch_id: "@@BID@@#1"`，`entries` 按 §6 顺序切分，不重叠、不遗漏。
- **7.3 回执**：JSON 后另起一行 `RECEIPT entries=@@N@@ uncertainties=N links=M selfcheck=PASS est_out=@@EST@@`；覆盖为单词 @@NW@@ + 短语 @@NP@@，标签目标 13/13（归属由检索判定，不作预置事实）。
"""

SAMPLE = [  # 内置样例（非 ECDICT 真实行，仅自检/演示，不得入库）
    ("run", "/rʌn/", "zk gk cet4", 410), ("schedule", "/ˈʃedjuːl/", "gk cet4 cet6", 1850),
    ("duplicate", "/ˈdjuːplɪkeɪt/", "cet6 ky", 4200), ("allocate", "/ˈæləkeɪt/", "cet6 ky bec", 3900),
    ("ambiguous", "/æmˈbɪɡjuəs/", "cet6 ky gre", 5100), ("charge", "/tʃɑːdʒ/", "zk gk cet4", 620),
    ("robust", "/rəʊˈbʌst/", "ky toefl gre", 4600), ("curriculum", "/kəˈrɪkjələm/", "tem4 tem8", 6800),
    ("break down", "", "gk cet4", 1200), ("in terms of", "", "cet4 cet6", 900),  # 短语 2 条：验证短语链路
]

class Abort(Exception):  # 参数/输入错误（code=2）或预算超限（code=3），main 统一映射退出码
    def __init__(self, msg, code=2): super().__init__(msg); self.code = code

def norm(w): return " ".join(w.strip().lower().split())     # 小写归一 + 压缩空白 → 去重键
def is_phrase(w): return " " in w or "-" in w               # 含空格/连字符即短语（F072 词组链路）
def parse_tags(raw): return tuple(t for t in (raw or "").lower().replace(",", " ").split() if t in TAGS)

def load_ecdict(path):
    """读 ECDICT csv：只取需要的列，缺列（旧版无 detail/audio）不报错"""
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        recs = [r for r in csv.DictReader(fh) if (r.get("word") or "").strip()]
    return [{"word": r["word"].strip(), "norm": norm(r["word"]), "pt": (r.get("phonetic") or "").strip(),
             "tags": parse_tags(r.get("tag")), "hint": "",
             "frq": int(r["frq"]) if (r.get("frq") or "").strip().isdigit() else 0} for r in recs]
def load_wordlist(path):
    """词表：每行 '词条' 或 '词条 | 关注点'，'#' 起为注释"""
    with open(path, encoding="utf-8") as fh:
        parts = [ln.split("#", 1)[0].strip().partition("|") for ln in fh if ln.split("#", 1)[0].strip()]
    return [{"word": w.strip(), "norm": norm(w), "pt": "", "tags": (), "frq": 0, "hint": h.strip()} for w, _, h in parts]

def sample_rows():  # 内置样例 → 与 csv 行同构
    return [{"word": w, "norm": norm(w), "pt": p, "tags": parse_tags(t), "frq": f, "hint": ""} for w, p, t, f in SAMPLE]

def select_words(rows, opts):
    """按标签/词频/词长/短语过滤 + 去重 + 确定性抽样"""
    want = {t for t in opts.tags.lower().replace(" ", "").split(",") if t}
    if want - set(TAGS):
        raise Abort("未知考试标签：%s（可选：%s）" % (",".join(sorted(want - set(TAGS))), ",".join(TAGS)))
    kept, seen = [], set()
    for r in rows:
        if (r["norm"] in seen or not opts.min_len <= len(r["word"]) <= opts.max_len or (want and not set(r["tags"]) & want)
                or (opts.max_freq and not 0 < r["frq"] <= opts.max_freq) or (opts.mode == "phrase" and not is_phrase(r["word"]))
                or (opts.mode == "word" and is_phrase(r["word"]))):
            continue
        seen.add(r["norm"])
        kept.append(r)
    kept.sort(key=lambda r: (r["frq"] == 0, r["frq"], r["norm"]))  # 已知高频在前
    random.Random(opts.seed).shuffle(kept)                          # 同 seed 可复跑
    return kept

def plan_batches(words, opts):
    """切批：每批 ≤ min(max-words, 预算可容纳数)，并逐批复核估算"""
    room = (opts.max_est_tokens - HEADER_TOKENS) // opts.tokens_per_word
    if room < 1:
        raise Abort("max-est-tokens=%d 连 1 条都放不下" % opts.max_est_tokens, 3)
    size = min(opts.max_words, int(room))
    batches = [words[i:i + size] for i in range(0, len(words), size)]
    for b in batches:
        if len(b) * opts.tokens_per_word + HEADER_TOKENS > opts.max_est_tokens:
            raise Abort("单批估算超预算 %d" % opts.max_est_tokens, 3)
    return batches

def check_coverage(words, batches):
    """覆盖率校验：每词恰好出现一次（判据可失败——少一条必须返回 False）"""
    flat = [w["norm"] for b in batches for w in b]
    ok = len(flat) == len(words) == len(set(flat)) and sorted(flat) == sorted(w["norm"] for w in words)
    return ok, "覆盖 %d / 输入 %d 条" % (len(flat), len(words))

def render_batch(bid, batch, opts, now, source, mode):
    """渲染单批文档：字段表 + 词表就地生成，一次性替换任务头占位符"""
    est = len(batch) * opts.tokens_per_word + HEADER_TOKENS
    nw = sum(1 for r in batch if not is_phrase(r["word"]))
    rows = ["| # | 字段 | 类型 | 必填 | 说明 |", "|---:|---|---|---|---|"]
    rows += ["| %d | `%s` | %s | %s | %s |" % (i, n, t, rq, d) for i, (n, t, rq, d) in enumerate(FIELDS, 1)]
    tbl = ["| # | 词条 | 类型 | 音标(英) | 考试标签 | frq | 关注点 |", "|---:|---|---|---|---|---:|---|"]
    tbl += ["| %d | %s | %s | %s | %s | %s | %s |" % (i, r["word"], "短语" if is_phrase(r["word"]) else "单词",
                                                     r["pt"] or "-", " ".join(r["tags"]) or "-", r["frq"] or "-",
                                                     r["hint"] or "-") for i, r in enumerate(batch, 1)]
    sub = {"@@BID@@": bid, "@@N@@": str(len(batch)), "@@EST@@": "{:,}".format(est), "@@SCHEMA@@": SCHEMA,
           "@@NW@@": str(nw), "@@NP@@": str(len(batch) - nw), "@@TPW@@": "{:,}".format(opts.tokens_per_word),
           "@@HDR@@": "{:,}".format(HEADER_TOKENS), "@@LIMIT@@": "{:,}".format(OUTPUT_LIMIT), "@@VERSION@@": VERSION,
           "@@RATIO@@": "%.1f" % (100.0 * est / OUTPUT_LIMIT), "@@MARGIN@@": "%.0f" % (100.0 - 100.0 * est / OUTPUT_LIMIT),
           "@@USABLE@@": "{:,}".format(int(OUTPUT_LIMIT * USABLE_RATIO)), "@@NOW@@": now, "@@SOURCE@@": source,
           "@@MODE@@": mode, "@@FIELDS@@": "\n".join(rows), "@@WORDS@@": "\n".join(tbl)}
    text = TPL
    for k, v in sub.items():
        text = text.replace(k, v)
    return text
def build(opts, now=None):
    """纯计算：返回 ([(批次号, 文档)], manifest)；不写盘，便于自检逐字节对拍"""
    now = now or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if opts.wordlist:
        if not os.path.exists(opts.wordlist):
            raise Abort("找不到 --wordlist：%s" % opts.wordlist)
        rows, mode, what = load_wordlist(opts.wordlist), "wordlist", "词表文件 %s" % opts.wordlist
    elif opts.input and os.path.exists(opts.input):
        rows, mode, what = load_ecdict(opts.input), "ecdict", opts.input
    else:
        rows, mode, what = sample_rows(), "builtin-sample", "内置样例（%s 不存在，未联网）" % opts.input
    words = select_words(rows, opts)
    if not words:
        raise Abort("过滤后无词条：放宽 --tags / --max-freq / --min-len / --mode")
    batches = plan_batches(words, opts)
    if not check_coverage(words, batches)[0]:
        raise Abort("切批自检失败：词条未恰好覆盖一次")
    source = "%s（%d %s）" % (what, len(rows), "行" if mode == "ecdict" else "条")
    docs, mb, total = [], [], 0
    for no, b in enumerate(batches, 1):
        bid, est = "batch-%03d" % no, len(b) * opts.tokens_per_word + HEADER_TOKENS
        total += est
        docs.append((bid, render_batch(bid, b, opts, now, source, mode)))
        mb.append({"batch_id": bid, "file": bid + ".md", "words": len(b), "est_tokens": est, "words_list":
                   [w["word"] for w in b]})
    manifest = {"generator": "extract_word_batches.py", "generator_version": VERSION, "schema": SCHEMA, "generated_at": now,
                "source": {"mode": mode, "detail": source, "license_note": "ECDICT 的 MIT 仅覆盖代码；"
                           "数据权利链与 BNC 频次再分发见索引 Ch4 §4.6.1，入库前须法务确认",
                           "params": {k: getattr(opts, k) for k in ("seed", "max_words", "max_est_tokens",
                                                                   "tokens_per_word", "tags", "mode")}},
                "totals": {"words": len(words), "batches": len(batches), "est_tokens": total,
                           "usage_ratio": round(total / float(OUTPUT_LIMIT), 3)},
                "batches": mb}
    return docs, manifest
def write_outputs(docs, manifest, out_dir):
    """落盘：批次文档 + manifest.json（UTF-8 / LF）"""
    os.makedirs(out_dir, exist_ok=True)
    payloads = [(bid + ".md", text) for bid, text in docs]
    payloads.append(("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"))
    for name, text in payloads:
        with open(os.path.join(out_dir, name), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
def self_test():
    """内置 10 词自检：切词 / 分批不超限 / 头自包含 / 可复跑 / 落盘 / 越限拒绝 / 判据可失败"""
    o = argparse.Namespace(input=None, wordlist=None, tags="", max_freq=0, min_len=1, max_len=40, mode="any",
                           max_words=4, max_est_tokens=288000, tokens_per_word=3500, out="batches", seed=7)
    now, res = "2026-10-22T00:00:00Z", []

    def chk(name, cond):
        res.append(bool(cond))
        print("%s %s" % ("PASS" if cond else "FAIL", name))

    docs, man = build(o, now=now)
    chk("切词 10 条 / 每批 ≤ 4 词且 ≤ 288000 token", man["totals"]["words"] == 10 and
        all(b["words"] <= 4 and b["est_tokens"] <= 288000 for b in man["batches"]))  # 切词 + 分批 + 不超限
    chk("可复跑：同 seed 逐字节一致", docs == build(o, now=now)[0])
    chk("manifest 含批次号/词数/估算/来源/时间", {"batches", "totals", "source", "generated_at"} <= set(man) and man["totals"]["words"] == 10)
    try:
        build(argparse.Namespace(**dict(vars(o), max_est_tokens=1000)), now=now)
        chk("越限拒绝：预算 1000 应报错", False)
    except Abort as exc:
        chk("越限拒绝：预算 1000 抛 Abort(code=3)", exc.code == 3)
    w = select_words(sample_rows(), o)
    bad = [list(b) for b in plan_batches(w, o)]
    bad[-1].pop()  # 人为弄坏：少一条 → 覆盖校验必须报错（证明判据不是恒真）
    chk("判据可失败：删一条后覆盖校验返回 False", not check_coverage(w, bad)[0])
    print("\n自检结果：%d 项，失败 %d 项" % (len(res), res.count(False)))
    return 0 if all(res) else 1
def main(argv=None):
    """CLI：解析参数 → 打印估算 → 超限拒绝 → 落盘"""
    ap = argparse.ArgumentParser(description="从开放词典切片词条，生成 AI 补全批次文档（仅标准库）")
    ap.add_argument("--input", default="ecdict.csv", help="ECDICT csv 路径（不存在则用内置样例）")
    ap.add_argument("--wordlist", help="词表：每行 '词条' 或 '词条 | 关注点'")
    ap.add_argument("--tags", default="", help="考试标签过滤（13 个，逗号分隔）")
    ap.add_argument("--max-freq", type=int, default=0, help="词频上限（frq 列，0=不过滤）")
    ap.add_argument("--min-len", type=int, default=1, help="词长下限（含空格）")
    ap.add_argument("--max-len", type=int, default=40, help="词长上限")
    ap.add_argument("--mode", choices=("any", "word", "phrase"), default="any", help="只取单词 / 只取短语")
    ap.add_argument("--max-words", type=int, default=60, help="每批词数上限（建议 40–60）")
    ap.add_argument("--max-est-tokens", type=int, default=int(OUTPUT_LIMIT * USABLE_RATIO), help="每批估算 token 上限")
    ap.add_argument("--tokens-per-word", type=int, default=TPW, help="每词条输出 token 经验值")
    ap.add_argument("--seed", type=int, default=20261022, help="抽样种子（同 seed 可复跑）")
    ap.add_argument("--out", default="batches", help="输出目录（相对路径，默认 batches）")
    ap.add_argument("--self-test", action="store_true", help="内置 10 词自检，失败非零退出")
    opts = ap.parse_args(argv)
    if opts.self_test:
        return self_test()
    try:
        docs, man = build(opts)
        # 每批独立一次 AI 调用：预算约束是"单批 ≤288k"，不是"总量"。
        # 总量只做提示，不拒绝；单批超限在 plan_batches 已硬失败。
        total, usable = man["totals"]["est_tokens"], int(OUTPUT_LIMIT * USABLE_RATIO)
    except Abort as exc:
        print("拒绝生成：%s" % exc, file=sys.stderr)
        return exc.code
    print("估算：%d 词 → %d token / 上限 %d（%.1f%%，余量 %.0f%%）· %d 批 → %s" % (
        man["totals"]["words"], total, OUTPUT_LIMIT, 100.0 * total / OUTPUT_LIMIT,
        100.0 - 100.0 * total / OUTPUT_LIMIT, man["totals"]["batches"],
        ", ".join("%s(%d 词)" % (b["batch_id"], b["words"]) for b in man["batches"])))
    write_outputs(docs, man, opts.out)
    print("已写出：%s/（%d 个批次 + manifest.json）" % (opts.out, len(docs)))
    return 0

if __name__ == "__main__":
    sys.exit(main())
