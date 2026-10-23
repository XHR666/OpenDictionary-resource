# OpenDictionary-resource

OpenDictionary 的资源清单、构建脚本与发布物仓库（不包含 App 代码）。

## 内容

| 路径 | 说明 |
|---|---|
| `manifest/` | 资源清单契约与示例（index / resource manifest / restricted 资源） |
| `scripts/` | 词典构建、词表采集与资源校验脚本 |
| `LICENSES/` | 许可登记与第三方来源清单 |
| `NOTICE` | 按内容类型的许可说明 |

## 构建

```bash
python3 scripts/build_lexicon_db.py --help
bash scripts/check-resources.sh
```

生成的数据库、模型与原始数据体积较大，默认输出到本地工作目录，不提交到仓库。

## 许可

- 代码（`scripts/`）：AGPL-3.0-or-later，见 `LICENSE-CODE`。
- 项目自编文档/数据/manifest：CC BY-NC-SA 4.0，见 `LICENSE`。
- 第三方数据保持原许可，见 `NOTICE` 与 `LICENSES/README.md`。

## 相关仓库

- App 源码：<https://github.com/XHR666/OpenDictionary>
- APK 预发布更新源：<https://github.com/XHR666/OpenDictionary-apk>
