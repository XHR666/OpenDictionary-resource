# 资源许可登记（LICENSES）

原则：**每个资源一行，没有登记就不许发布。** 许可文本放本目录（文件名 = SPDX 或 `LicenseRef-*`）。

## 0. 代码许可 ≠ 第三方内容许可（必读）

- 本仓库脚本按 **GPL-3.0-or-later** 授权；但仓库/发布包里引用的**第三方名言、例句、词条、音频、字体、文本**版权归原权利人，**不在代码许可证的授权范围内**。
- 每条内容必须登记 `source_type`（self_written / pd / cc_by / cc_by_sa / user_imported / ai_generated / official_data）、`attribution`、`evidence_url`；风险分层：公共领域内容优先；短引用标注来源；禁止整段复制付费词典的例句编排。
- **禁止**复制任何词典（含开源词典）的例句编排；词典"例证/例句选择与编排"是高风险保护对象（参考：读书郎学习机抄袭《汉语大词典》例证被索赔 1024 万元案）。
- 用户导入内容**不入库、不随包分发**，只提供导入工具。

## 允许进入主路径（候选清单）

| SPDX / 条款 | 说明 | 需核实点 |
|---|---|---|
| `MIT` | ECDICT、Quotable 等 | 逐个仓库确认 LICENSE 文件 |
| `Apache-2.0` | AndroidX、llama.cpp(部分)、Wiktionary 工具链 | NOTICE 要求 |
| `CC0-1.0` / `PD` | Common Voice、Project Gutenberg、LibriVox（看具体录音） | "公共领域"按法域核实 |
| `CC-BY-4.0` | Open English WordNet 等 | 署名要求 |
| `CC-BY-SA-4.0` | Wiktionary、Wikipedia、Tatoeba（句子）等 | 传染性：衍生文本需同许可，数据聚合边界要写清 |
| `CC-BY-2.0-FR` | Tatoeba 句子数据 | 音频许可单独核对 |

## 禁止进入主路径

| 来源 | 原因 |
|---|---|
| COCA（词频/搭配） | 明确禁止商业使用 |
| Datamuse API | 免费层仅非商业 |
| Merriam-Webster / Collins / Oxford API | 非商用免费或条款不明 |
| OpenSubtitles / 影视字幕 | 商业使用被禁止，译者版权 |
| eSpeak NG（内置） | GPLv3 传染性 + 音质不适合 |
| isdict-api（Oxford 部分） | 许可不明确 |
| Cloudflare R2 | 免费层有限量，不符合"无有限量"约束 |
| DANTE / ProPOSEL（若许可仅限研究） | **待核实**：研究许可与商用冲突时不得进主路径 |
| 任何逆向 API | 法律风险 |

## 登记格式

| 资源 id | 上游 | 版本 | 许可 | 证据 URL | commercial_ok | 使用位置 |
|---|---|---|---|---|---|---|
| （待登记） | | | | | | |

## 外部补充词表（2026-10-22 最终核实，D23）

| 来源 | 用于 | 许可 | 义务/状态 | 备注 |
|---|---|---|---|---|
| `2ndLA/english-phrases` `lists/senior.txt` | **高中/高考常见短语** `gk_phrases`（2,808 条） | **CC BY-SA 4.0**（LICENSE 原文已核） | 署名 + 相同方式共享 | **严格说是"高中"短语，非官方高考大纲**；产品文案须写"高中/高考常见短语"；需人工抽检 |
| `chrisdeaner/sat-prep` `sat_vocabulary.csv` | `sat` 标签（275 词，主源） | **MIT** | 保留版权与许可声明 | 自述来自 2024–2026 官方 SAT 题，置信度高 |
| `hkperceptionlab/sat-vocab` `public/sat1000.json` | `sat` 标签（991 词，辅源） | **MIT** | 保留版权与许可声明 | 上游未注明（可能与"1000 SAT words"同源），置信度中；两源去重后 **1,171** |
| **不采用**：OpenEtymology TEM8（与无许可 mahavivo 星标表 96.9% 重合，许可链存疑）、TEM4/BEC（无可再分发授权）、GMAT 799（MIT 但来源未注明、词表偏基础，弱条件）、kajweb/qwerty/LinXueyuanStdio/mikigo/maimemo-export/100-vocabulary-lib/superword（抓自商业 App/出版书） | — | — | — | 只参考结构，不取数据 |

> 说明：外部词表原始数据只存 `work/external/`（不入库）；合并逻辑在 `scripts/build_lexicon_db.py --extra-tags/--phrases`，抓取脚本 `scripts/fetch_external_wordlists.py`（可复跑，含自检）。
## 短语/习语/拉丁语库（D26）

| 来源 | 用于 | 许可 | 说明 |
|---|---|---|---|
| ECDICT 多词条目（过滤后） | `phrases_ecdict` 350,908 条 | MIT（数据链待法务） | 候选库，需人工抽检；过滤数字/专名/超长 |
| 2ndLA/english-phrases | `gk_phrases` 2,808 / `tem4_phrases` 1,219 / `tem8_phrases` 2,429 | CC BY-SA 4.0 | 署名+同许可 |
| 项目自编 `scripts/data/latin-phrases.csv` | `latin_phrases` 54 条 | **CC0-1.0**（本项目自编） | 常见拉丁语短语与中文释义；可自由使用 |
