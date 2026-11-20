#!/usr/bin/env bash
# 生成 Xcode 工程并构建 PersonalIntelligenceHub.app（Debug，免签名）。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SPEC="$ROOT/App/project.yml"
PROJECT="$ROOT/App/PersonalIntelligenceHub.xcodeproj"
DERIVED_DATA="$ROOT/build/DerivedData"
APP="$DERIVED_DATA/Build/Products/Debug/PersonalIntelligenceHub.app"

if ! command -v xcodegen >/dev/null 2>&1; then
  echo "错误：未找到 xcodegen，请先安装（brew install xcodegen）。" >&2
  exit 1
fi

if [ ! -f "$SPEC" ]; then
  echo "错误：未找到工程定义 $SPEC" >&2
  exit 1
fi

echo "==> 生成构建元数据（git commit / build time）"
python3 "$ROOT/Scripts/build_metadata.py"

echo "==> xcodegen generate ($SPEC)"
xcodegen generate --spec "$SPEC"

echo "==> xcodebuild (-project App/PersonalIntelligenceHub.xcodeproj -scheme PersonalIntelligenceHub)"
xcodebuild \
  -project "$PROJECT" \
  -scheme PersonalIntelligenceHub \
  -configuration Debug \
  -derivedDataPath "$DERIVED_DATA" \
  build

if [ ! -d "$APP" ]; then
  echo "错误：构建完成但未找到 $APP" >&2
  exit 1
fi

echo "APP_PATH=$APP"
