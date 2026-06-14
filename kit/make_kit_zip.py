"""自己完結の引っ越しキットzipを生成する（現環境で実行）。

同梱物:
  コード:   collectors/ parsers/ pipeline/ db/ dashboard/ kit/（exports含む）
            dev/（再構築・増分収集に必要なスクリプトのみホワイトリスト）
  データ:   data/manual/ data/db/url_matrix.db data/db/defense_pillar.db
            data/db/jigyou_review.db
  ドキュメント: CLAUDE.md docs/ requirements.txt .streamlit/config.toml
  ※ data/raw/（10GB超キャッシュ）と procurement.db は同梱しない —
    新環境で kit/downloader.py + kit/rebuild_all.py が再生成する。
  ※ .streamlit/secrets.toml（パスワード）は除外し、example を同梱。

実行:
  python kit/make_kit_zip.py                          # → defense_procurement_kit_<date>.zip
  python kit/make_kit_zip.py --include-choutatsuyotei-pdf  # 66MBの原本PDFも同梱
  python kit/make_kit_zip.py --output D:/path/kit.zip
"""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ディレクトリ丸ごと（除外パターンは _excluded で判定）
INCLUDE_DIRS = [
    "collectors", "parsers", "pipeline", "db", "dashboard", "kit",
    "data/manual", "docs",
]
INCLUDE_FILES = [
    "CLAUDE.md", "requirements.txt",
    "data/db/url_matrix.db", "data/db/defense_pillar.db",
    "data/db/jigyou_review.db",
    ".streamlit/config.toml",
]
# dev/ は再構築・増分収集・修復に必要なものだけ
DEV_WHITELIST = [
    "assign_pillar_fy2023.py",        # 7本柱キーワード分類（FY増分用）
    "assign_pillar_semantic.py",      # セマンティック分類（GPU環境を得た場合用）
    "recompute_atla_requesting_org.py",  # ATLA要求元再計算（増分用）
    "manual_atla_overrides.py",       # 手動オーバーライド辞書（上の依存）
    "apply_fallback_50oku.py",        # 50億超手動判定（rowid注意・記録として）
    "insert_equipment_master.py",     # 装備品マスター
    "load_choutatsuyotei_pdf.py",     # 調達予定品目表（再収集用）
    "load_choutatsuyotei_xlsx.py",
    "load_pillar_sources.py",         # 7本柱根拠ソース収集
    "load_seibi_keikaku_gaiyou.py",   # 整備計画概要
    "match_kenkyuu_hyouka_fallback.py",
]

EXCLUDE_PARTS = {"__pycache__", ".venv", "node_modules", ".git"}
EXCLUDE_SUFFIXES = {".pyc", ".log", ".tmp"}

SECRETS_EXAMPLE = 'APP_PASSWORD = "ここにダッシュボードのパスワードを設定"\n'


def _excluded(p: Path) -> bool:
    if any(part in EXCLUDE_PARTS for part in p.parts):
        return True
    if p.suffix.lower() in EXCLUDE_SUFFIXES:
        return True
    if p.name == "secrets.toml":
        return True
    # kit/exports のランタイム生成物（manifest・レポート）は除外
    if p.name in {"download_manifest.jsonl", "rebuild_log.json",
                  "verify_report.json", "verify_missing_urls.txt",
                  "replay_gaps_report.json", "missing_urls.txt",
                  "import_unmatched.json", "import_ambiguous.json",
                  "kit_manifest.json"}:
        return True
    return False


def collect_files(include_chy_pdf: bool) -> list[Path]:
    files: list[Path] = []
    for d in INCLUDE_DIRS:
        base = PROJECT_ROOT / d
        if d == "dev":
            continue
        if not base.exists():
            print(f"  WARN: {d} が存在しません")
            continue
        for p in base.rglob("*"):
            if p.is_file() and not _excluded(p):
                files.append(p)
    for f in INCLUDE_FILES:
        p = PROJECT_ROOT / f
        if p.exists():
            files.append(p)
        else:
            print(f"  WARN: {f} が存在しません")
    for name in DEV_WHITELIST:
        p = PROJECT_ROOT / "dev" / name
        if p.exists():
            files.append(p)
        else:
            print(f"  WARN: dev/{name} が存在しません")
    if include_chy_pdf:
        for p in (PROJECT_ROOT / "data" / "choutatsuyotei").rglob("*"):
            if p.is_file() and not _excluded(p):
                files.append(p)
    return sorted(set(files))


def main() -> None:
    parser = argparse.ArgumentParser(description="引っ越しキットzip生成")
    parser.add_argument("--output",
                        default=str(PROJECT_ROOT /
                                    f"defense_procurement_kit_"
                                    f"{datetime.now():%Y%m%d}.zip"))
    parser.add_argument("--include-choutatsuyotei-pdf", action="store_true",
                        help="data/choutatsuyotei の原本PDF(66MB)も同梱")
    args = parser.parse_args()

    files = collect_files(args.include_choutatsuyotei_pdf)
    out = Path(args.output)

    manifest: dict = {"created_at": datetime.now().isoformat(),
                      "files": {}}
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            rel = p.relative_to(PROJECT_ROOT).as_posix()
            zf.write(p, rel)
            manifest["files"][rel] = {
                "bytes": p.stat().st_size,
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest()[:16],
            }
        zf.writestr(".streamlit/secrets.toml.example", SECRETS_EXAMPLE)
        zf.writestr("kit_manifest.json",
                    json.dumps(manifest, ensure_ascii=False, indent=1))

    total_mb = sum(v["bytes"] for v in manifest["files"].values()) / 1e6
    print(f"SUMMARY files={len(files)} uncompressed={total_mb:.0f}MB "
          f"zip={out.stat().st_size / 1e6:.0f}MB")
    print(f"出力: {out}")


if __name__ == "__main__":
    main()
