#!/usr/bin/env bash
# 引っ越しキット 環境ブートストラップ（macOS / Linux）
# 使い方:  bash kit/setup_env.sh
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== Python 確認 ==="
PY=$(command -v python3 || command -v python) || {
  echo "Python が見つかりません。3.11+ をインストールしてください。"; exit 1; }
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' || {
  echo "Python 3.10+ が必要です"; exit 1; }
"$PY" --version

echo "=== venv 作成 ==="
[ -d "$ROOT/.venv" ] || "$PY" -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/python" -m pip install --upgrade pip --quiet

echo "=== 依存インストール ==="
"$ROOT/.venv/bin/python" -m pip install -r "$ROOT/kit/requirements_cpu.txt"

echo "=== スモークテスト ==="
"$ROOT/.venv/bin/python" -c "import requests, pandas, openpyxl, bs4, pdfplumber, rapidfuzz, streamlit, plotly; print('imports OK')"

echo ""
echo "SUMMARY setup=OK venv=$ROOT/.venv"
echo "以後は 'source $ROOT/.venv/bin/activate' してから実行してください。"
