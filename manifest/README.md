# 资源清单契约 v1（草案）

`resource-manifest.json` 由本仓库在每次资源发布时生成；App 仓库引用 `manifest_url + sha256`，
启动/更新时校验。字段变更 = 契约破坏，必须升 `manifest_version`。

## 顶层字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `manifest_version` | int | 是 | 契约版本，当前 `1` |
| `resource_version` | string | 是 | 与 git tag 一致，如 `v1.2.0` |
| `generated_at` | string | 是 | ISO-8601 |
| `min_app_version` | string | 是 | 兼容的最低 App 版本 |
| `entries` | array | 是 | 资源条目 |

## entry 字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | string | 是 | 全局唯一，如 `ecdict-core` |
| `kind` | enum | 是 | `lexicon` / `llm` / `tts` / `asr` / `audio` / `image` / `font` / `text` / `dict-data` |
| `version` | string | 是 | 资源自身版本 |
| `license` | string | 是 | SPDX 或明确条款名（如 `CC-BY-SA-4.0`、`PD`、`LicenseRef-DANTE-research-only`） |
| `commercial_ok` | bool | 是 | 是否允许商用；`false` 不得进入主路径 |
| `source_url` | string | 是 | 上游来源 URL |
| `path` | string | 是 | App 内落盘相对路径 |
| `size_bytes` | int | 是 | 安装后大小（压缩态另注 `packed_size_bytes`） |
| `sha256` | string | 是 | 文件哈希；App 校验 |
| `release_tag` | string | 是 | GitHub Release tag |
| `optional` | bool | 是 | 是否按需下载（默认不预置） |
| `source_type` | enum | 内容类必填 | `self_written` / `pd` / `cc_by` / `cc_by_sa` / `user_imported` / `ai_generated` / `official_data` |
| `attribution` | string | 内容类必填 | 应用内展示的署名文本（作者/来源/许可） |
| `evidence_url` | string | 内容类必填 | 许可或来源证据 URL |
| `author_death_year` | int | `source_type=pd` 必填 | 用于公共领域判定（中国/海外阈值不同，见 05 文档） |
| `note` | string | 否 | 备注 |

## 一致性规则

- 同一 `id` 的 `sha256` 变化 ⇒ `version` 必须递增。
- `commercial_ok=false` 的资源禁止进入主路径候选。
- 未在 `LICENSES/` 登记的许可不得发布。
- 资源仓库 tag 与 `resource_version` 不一致 ⇒ 发布失败。
- **内容类资源**（例句/名言/词卡/文本）缺 `source_type`、`attribution`、`evidence_url` 三者之一 ⇒ 发布失败；`source_type=pd` 时必须给 `author_death_year`（阈值按分发地区：中国大陆 50 年、海外 70 年，见 `docs/proj/05-例句与内容版权合规策略.md`）。
- **禁止** `source_type=self_written` 的内容实际抄自词典例句编排（抽检发现即整包回滚）。

## 受限资源（须用户授权，D24）

以下字段用于"不可默认分发、须用户明确授权"的资源（如来源存疑的考试词表）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `consent_required` | bool | 为 true 时，App 必须弹出风险确认，用户勾选后才允许下载 |
| `risk_level` | enum | `low` / `medium` / `high`；`high` 需二次确认 |
| `redistribution_note` | string | 风险说明（来源/许可问题/用户自行承担） |

- 受限资源**不得**出现在默认资源包/APK 内，也不得进入自动更新；只能由用户在"高级/风险资源"页手动勾选下载。
- 示例：`resource-manifest.restricted.example.json`（`restricted-words` 包，仅元数据，不含词条数据）。
- 发布建议：资源仓公开时，此类包建议仅放 Releases 并附风险声明；法务不通过时不得发布。
