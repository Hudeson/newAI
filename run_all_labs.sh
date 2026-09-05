#!/usr/bin/env bash
#
# 按由快到慢的顺序跑通全部实验。
#
#   bash run_all_labs.sh          # 快速集合：第 2 章走 --quick，第 4 章走 --quick
#   bash run_all_labs.sh --all    # 完整版：第 2、4 章都跑全量（第 4 章约 5 分钟）
#   bash run_all_labs.sh --log out/    # 同时把每章输出写进 out/labNN.log
#
# 必须在仓库根目录执行（否则 `import dive` 找不到）。

set -uo pipefail

cd "$(dirname "$0")"

FULL=0
LOGDIR=""
while [ $# -gt 0 ]; do
  case "$1" in
    --all) FULL=1; shift ;;
    --log) LOGDIR="${2:?--log 需要一个目录参数}"; shift 2 ;;
    -h|--help) sed -n '3,11p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "未知参数：$1（可用 --all / --log DIR）" >&2; exit 2 ;;
  esac
done

PY="${PYTHON:-python3}"
if ! "$PY" -c "import numpy" 2>/dev/null; then
  echo "找不到 NumPy。请先执行：$PY -m pip install numpy" >&2
  exit 1
fi
[ -n "$LOGDIR" ] && mkdir -p "$LOGDIR"

if [ "$FULL" -eq 1 ]; then
  QUICK2=""
  QUICK4=""
else
  QUICK2="--quick"
  QUICK4="--quick"
fi

# 每行：模块名 [额外参数...]
LABS=(
  "labs.lab09_gui_agent"
  "labs.lab10_agent_safety"
  "labs.lab03_knowledge_edit"
  "labs.lab08_multimodal"
  "labs.lab01_finetune"
  "labs.lab06_jailbreak"
  "labs.lab07_stega"
  "labs.lab11_rlhf"
  "labs.lab05_watermark"
  "labs.lab02_prompting_cot ${QUICK2}"
  "labs.lab04_math_reasoning ${QUICK4}"
)

FAILED=()
START_ALL=$SECONDS

for entry in "${LABS[@]}"; do
  # shellcheck disable=SC2086
  set -- $entry
  module="$1"; shift
  name="${module##*.}"

  printf '\n\033[1m===== %s %s =====\033[0m\n' "$name" "$*"
  start=$SECONDS
  if [ -n "$LOGDIR" ]; then
    "$PY" -m "$module" "$@" 2>&1 | tee "$LOGDIR/$name.log"
    status=${PIPESTATUS[0]}
  else
    "$PY" -m "$module" "$@"
    status=$?
  fi
  elapsed=$((SECONDS - start))

  if [ "$status" -eq 0 ]; then
    printf '\033[32m[完成]\033[0m %s（%d 秒）\n' "$name" "$elapsed"
  else
    printf '\033[31m[失败]\033[0m %s（退出码 %d）\n' "$name" "$status"
    FAILED+=("$name")
  fi
done

printf '\n\033[1m===== 总计 =====\033[0m\n'
printf '共 %d 个实验，用时 %d 秒。\n' "${#LABS[@]}" "$((SECONDS - START_ALL))"
if [ "${#FAILED[@]}" -eq 0 ]; then
  echo "全部通过。"
else
  printf '失败：%s\n' "${FAILED[*]}"
  exit 1
fi
