#!/usr/bin/env bash
# 本地一键:全量采集 + 信号计算 + 健康摘要 + 起本地预览
# 用法:./scripts/run_local.sh          完整流程
#       SKIP_SOURCES=fred,yahoo ./scripts/run_local.sh   跳过慢源调前端
set -euo pipefail
cd "$(dirname "$0")/.."

python3 -u -m pipeline.run_all
python3 -m pipeline.check_status || true   # 本地预览不因个别源失败而中断

echo
echo "预览: http://localhost:8000  (Ctrl-C 退出)"
python3 -m http.server 8000
