#!/usr/bin/env bash
# 启动已构建的 PersonalIntelligenceHub.app。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$ROOT/build/DerivedData/Build/Products/Debug/PersonalIntelligenceHub.app"

if [ ! -d "$APP" ]; then
  echo "错误：未找到 $APP，请先运行 Scripts/build_app.sh" >&2
  exit 1
fi

echo "==> open $APP"
open -n "$APP"
