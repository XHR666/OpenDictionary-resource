#!/usr/bin/env bash
# 资源仓库判据：体积 / 清单完整性 / 许可登记 · 规则见 ../../docs/ENGINEERING-RULES.md
# 原则：能失败才算判据（R1）；当前无资源时明确 SKIP，禁止静默通过
set -u

pass=0; fail=0; skip=0
ok() { pass=$((pass + 1)); echo "PASS  $1  ${2:-}"; }
ng() { fail=$((fail + 1)); echo "FAIL  $1  ${2:-}"; }
sk() { skip=$((skip + 1)); echo "SKIP  $1  ${2:-}"; }

# R01 已跟踪文件不得 >50MB（大二进制走 Releases）
if ! git rev-parse --verify HEAD >/dev/null 2>&1; then
  sk R01 "尚无首次提交，无已跟踪文件可检查"
else
  big=""
  while IFS= read -r f; do
    [ -f "$f" ] || continue
    s=$(stat -c%s "$f")
    [ "$s" -gt 52428800 ] && big="$big $f($s)"
  done < <(git ls-files)
  if [ -n "$big" ]; then ng R01 "超过 50MB 的已跟踪文件:$big"; else ok R01 "无 >50MB 的已跟踪文件"; fi
fi

# R02 manifest 存在且 JSON 可解析
if [ -f manifest/resource-manifest.json ]; then
  if command -v jq >/dev/null && jq -e . manifest/resource-manifest.json >/dev/null 2>&1; then
    ok R02 "manifest JSON 可解析"
  else
    ng R02 "manifest JSON 不可解析（jq 缺失或语法错误）"
  fi
else
  sk R02 "manifest/resource-manifest.json 不存在（资源尚未登记）"
fi

# R03 manifest 字段完整性 + commercial_ok=false 不得进主路径（条目存在后才可判）
if [ -f manifest/resource-manifest.json ] && command -v jq >/dev/null; then
  missing=$(jq -r '.entries[]? | select((.id|not) or (.license|not) or (.sha256|not) or (.commercial_ok|not)) | .id // "?"' manifest/resource-manifest.json 2>/dev/null)
  if [ -n "$missing" ]; then ng R03 "缺必填字段条目: $missing"; else ok R03 "manifest 条目必填字段齐全（或为空）"; fi
else
  sk R03 "无可校验的 manifest"
fi

# R04 许可登记表存在
if [ -f LICENSES/README.md ]; then
  sk R04 "许可登记表存在；'禁止源零引用'判据尚未实现（需扫描 manifest）"
else
  ng R04 "缺少 LICENSES/README.md"
fi

echo "===== ${pass} 通过 / ${fail} 失败 / ${skip} 跳过 ====="
exit $(( fail ? 1 : 0 ))
