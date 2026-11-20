#!/usr/bin/env bash
# 将 PIH Backend 打包进 App Bundle 的 Resources/sidecar/。
# 用法：Scripts/package_sidecar.sh <目标 App Bundle 路径>
#
# 打包内容：
#   - 后端所有源码（排除 .venv、tests、__pycache__）
#   - venv site-packages（排除 pytest/pip 等开发工具）
#
# 运行时要求本机有 Homebrew Python 3.14+（/opt/homebrew/bin/python3）。
# 这是首次本机安装的务实方案，后续可升级为完全独立的 Python.framework 打包。

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT/Backend"
VENV_SITE="$BACKEND_DIR/.venv/lib/python3.14/site-packages"

if [ $# -lt 1 ]; then
  echo "用法：$0 <目标 App Bundle 路径>" >&2
  exit 1
fi

APP_BUNDLE="$1"
SIDECAR_DIR="$APP_BUNDLE/Contents/Resources/sidecar"

if [ ! -d "$APP_BUNDLE" ]; then
  echo "错误：App Bundle 不存在：$APP_BUNDLE" >&2
  exit 1
fi

if [ ! -d "$BACKEND_DIR" ]; then
  echo "错误：Backend 目录不存在：$BACKEND_DIR" >&2
  exit 1
fi

if [ ! -d "$VENV_SITE" ]; then
  echo "错误：venv site-packages 不存在：$VENV_SITE" >&2
  exit 1
fi

echo "==> 清理旧的 sidecar 目录"
rm -rf "$SIDECAR_DIR"
mkdir -p "$SIDECAR_DIR"

echo "==> 复制后端源码"
# main.py 放根目录
cp "$BACKEND_DIR/main.py" "$SIDECAR_DIR/main.py"

# 构建元数据：优先使用已生成的 build_meta.json，缺失时现生成（不影响运行时依赖 git）。
if [ ! -f "$BACKEND_DIR/build_meta.json" ]; then
  python3 "$ROOT/Scripts/build_metadata.py" >/dev/null
fi
cp "$BACKEND_DIR/build_meta.json" "$SIDECAR_DIR/build_meta.json"

# 后端子目录（排除 tests、scripts、__pycache__）
for subdir in ai_engine api collectors core database event_intelligence services; do
  if [ -d "$BACKEND_DIR/$subdir" ]; then
    mkdir -p "$SIDECAR_DIR/$subdir"
    rsync -a \
      --exclude='__pycache__' \
      --exclude='*.pyc' \
      --exclude='.pytest_cache' \
      "$BACKEND_DIR/$subdir/" "$SIDECAR_DIR/$subdir/"
  fi
done

echo "==> 复制 venv site-packages（仅运行时依赖）"
mkdir -p "$SIDECAR_DIR/site-packages"

# 运行时依赖白名单（pip freeze 排除 pytest/pip/setuptools/wheel 等开发工具）
RUNTIME_DEPS=(
  annotated_doc
  annotated_types
  anyio
  certifi
  click
  defusedxml
  fastapi
  feedparser
  h11
  httpcore
  httpx
  idna
  iniconfig
  opentelemetry
  packaging
  pluggy
  pydantic
  pydantic_core
  pygments
  starlette
  typing_inspection
  uvicorn
  # 顶层 .py 文件
  py.py
  sgmllib.py
  typing_extensions.py
)

for dep in "${RUNTIME_DEPS[@]}"; do
  src="$VENV_SITE/$dep"
  if [ -e "$src" ]; then
    dst="$SIDECAR_DIR/site-packages/$dep"
    if [ -d "$src" ]; then
      rsync -a "$src/" "$dst/"
    else
      cp "$src" "$dst"
    fi
  fi
done

# 同时复制所有 dist-info（避免 import 时报版本错误）
for dist in "$VENV_SITE"/*.dist-info; do
  if [ -d "$dist" ]; then
    name="$(basename "$dist")"
    # 跳过 pytest/pip/setuptools/wheel 等开发工具的 dist-info
    case "$name" in
      pytest-*|pip-*|setuptools-*|wheel-*|pluggy-*) continue ;;
    esac
    cp -R "$dist" "$SIDECAR_DIR/site-packages/$name"
  fi
done

echo "==> 验证 site-packages 导入"
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH="$SIDECAR_DIR/site-packages:$SIDECAR_DIR" /opt/homebrew/bin/python3 -c "
import sys
sys.path.insert(0, '$SIDECAR_DIR')
import fastapi, uvicorn, feedparser, defusedxml, httpx, pydantic
print('sidecar site-packages verification OK')
print('fastapi', fastapi.__version__, 'uvicorn', uvicorn.__version__)
"

# 校验过程（以及任何本地运行）都不应在 Bundle 内留下字节码；签名要求资源密封稳定。
echo "==> 清理 __pycache__ / *.pyc"
find "$SIDECAR_DIR" -type d -name "__pycache__" -prune -exec rm -rf {} +
find "$SIDECAR_DIR" -type f -name "*.pyc" -delete

echo "==> Sidecar 打包完成"
echo "目标目录：$SIDECAR_DIR"
du -sh "$SIDECAR_DIR"
