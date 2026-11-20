#!/usr/bin/env bash
# 开发期手动启动 PIH Sidecar。
#
# Token 只能通过环境变量传入，脚本不会生成、也不会打印 Token。
# 自行生成 Token（43 字符 base64url，去 padding）：
#   export PIH_SIDECAR_TOKEN="$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '=')"
#
# 可选环境变量：PIH_PORT（默认 0，由内核分配）、PIH_DATA_DIR（默认用户数据目录）。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT/Backend/.venv/bin/python"
ENTRY="$ROOT/Backend/main.py"

if [ -z "${PIH_SIDECAR_TOKEN:-}" ]; then
  echo "错误：未设置 PIH_SIDECAR_TOKEN。请先执行：" >&2
  echo "  export PIH_SIDECAR_TOKEN=\"\$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '=')\"" >&2
  exit 1
fi

if [ ! -x "$PYTHON" ]; then
  echo "错误：未找到 $PYTHON，请先创建 Backend/.venv" >&2
  exit 1
fi

cd "$ROOT"
exec "$PYTHON" "$ENTRY"
