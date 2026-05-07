"""ATLA中央調達契約の手動要求元オーバーライド辞書。

`recompute_atla_requesting_org.py` から参照される。
choutatsuyotei_fuzzy が見つからなかった大型案件・特殊案件を補完する。

優先順位はメインスクリプト側で決定される（現状は step 4d, conf=0.85）。

エントリ追加方針:
  - 1件あたり10億円以上の大型案件、または明確に要求元が特定できる定型案件
  - ソース根拠（行政事業レビュー、防衛白書、報道等）を note 列に明記
  - 半角カッコ・全角カッコ、空白の揺れは正規表現で吸収
"""
from __future__ import annotations

import re

# ─── EXACT_OVERRIDES: normalize_item_name 済みキー → (org, note) ──────────────
# normalize_item_name() は NFKC + 句読点除去 + lower。
# 完全一致したいときに使う（O(1) 検索）。
EXACT_OVERRIDES: dict[str, tuple[str, str]] = {}


# ─── PATTERN_OVERRIDES: 部分一致（正規化前の元文字列に対して適用） ──────────
# (パターン, 要求元, note) の順
PATTERN_OVERRIDES: list[tuple[re.Pattern[str], str, str]] = [
    # 情報本部関連
    (re.compile(r"衛星コンステレーション"), "DIH",
     "PfWS（小型衛星画像取得）契約。要求元は情報本部"),
    (re.compile(r"画像情報収集衛星"), "DIH", "情報本部所掌"),

    # 統合幕僚監部関連
    (re.compile(r"民間海上輸送|民海輸|民間船舶.*輸送"), "JS",
     "民間海上輸送力活用事業（統合幕僚監部所掌）"),
    (re.compile(r"日米連携機能"), "JS", "統合運用関連"),
    (re.compile(r"統合.*演習|統合運用基盤"), "JS", ""),

    # 航空自衛隊関連（無人機・F-35シミュレータ等）
    (re.compile(r"滞空型無人機|グローバルホーク|RQ-?4"), "ASDF",
     "RQ-4 グローバルホーク（空自運用）"),
    (re.compile(r"幕僚業務用端末.*空"), "ASDF", ""),

    # 陸上自衛隊関連
    (re.compile(r"極超音速誘導弾|島嶼防衛用高速滑空弾"), "GSDF",
     "陸自スタンドオフ装備"),
]


def find_manual_override(raw_name: str | None) -> tuple[str, str] | None:
    """契約名（生）に対しオーバーライドを検索。

    Returns:
        (要求元, note) もしくは None
    """
    if not raw_name:
        return None
    for pattern, org, note in PATTERN_OVERRIDES:
        if pattern.search(raw_name):
            return (org, note)
    return None


def find_manual_override_norm(norm_name: str) -> tuple[str, str] | None:
    """normalize_item_name 済みキーで検索（EXACT_OVERRIDES 用）。"""
    if not norm_name:
        return None
    return EXACT_OVERRIDES.get(norm_name)
