"""
P8 親コード残存109件を P81/P82/P83/P84 に自動分類。
--dry-run: DBに書かない（デフォルト）
--apply  : /tmp コピー経由で本番適用
"""
import re, sys, os, shutil, sqlite3, argparse, unicodedata
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
DB   = ROOT / "data/db/defense_pillar.db"
TMP  = Path(os.environ.get("TEMP", "C:/Temp")) / "defense_pillar_work.db"

# ── 分類ルール（先にマッチしたものが優先）────────────────────────────────
# (target_pillar_id, pillar_name, [正規表現パターン])
RULES = [
    # P82: 研究開発（研究・実証・試作が名前に入る）
    (82, "研究開発", [
        r"に関する研究$",
        r"の研究$",
        r"技術の研究$",
        r"運用実証$",
        r"実証$",
        r"先行実証$",
        r"試作$",
        r"技術実証",
        r"戦術ＡＩ衛星",
        r"ＡＩ導入に係る部外力の活用",
        r"補給倉庫の自動化",
        r"生成ＡＩ活用の検討",
        r"ＡＩを活用した公開情報",
        r"陸自ＡＩ基盤の整備",
        r"サイバー領域における意思決定支援システムの整備",
        r"地上電波測定装置の換装",
        r"オンプレミス環境での生成ＡＩ",
    ]),
    # P83: 基地対策
    (83, "基地対策", [
        r"施設及びインフラの強靱化",
        r"施設及びインフラの強靭化",
        r"施設の効率化",
        r"温室効果ガス排出の削減",
    ]),
    # P81: 防衛生産基盤の強化
    (81, "防衛生産基盤の強化", [
        r"防衛装備品の防衛力向上とレジリエンス強化",
        r"計画的.*安定的.*効率的な取得",
        r"独自仕様の絞り込み",
        r"工数.*工程.*精査",
        r"事業に係る見直し",
        r"装備品の運用停止.*用途廃止",
        r"用途廃止$",
        r"信頼性回復$",
        r"定期修理の見直し",
        r"ファミリー化$",
        r"誘導弾の信頼性",
    ]),
    # P84: 教育訓練費・燃料費等
    (84, "教育訓練費・燃料費等", [
        r"訓練の実施$",
        r"演習.*の実施$",
        r"共同統合演習",
        r"共同統合防空",
        r"共同訓練$",
        r"合同演習$",
        r"指揮所演習",
        r"大規模広域訓練",
        r"実動訓練$",
        r"防勢対航空訓練",
        r"能力構築支援",
        r"パートナーシップ",
        r"への参加$",
        r"講師派遣",
        r"海賊対処",
        r"情報収集活動",
        r"人道支援.*災害救援",
        r"二国間.*多国間訓練",
        r"訓練、教育、人材育成",
        r"ＡＩ人材の育成",
        r"ＡＩ講習の実施",
        r"ＰＫＯセンター",
        r"三角パートナーシップ",
        r"ビエンチャン",
        r"ＡＳＥＡＮ",
        r"自衛隊員の生活.*勤務.*環境の改善",
        r"衛生機能の強化",
        r"インド太平洋.*派遣",
        r"中東地域",
        r"ソマリア沖",
        r"インドにおける",
        r"ミクロネシア",
        r"アフリカ諸国",
        r"の改編$",
        r"[をの]新設",
        r"[をの]創設",
        r"[をの]新編",
        r"の下での取組$",
        r"情報保全",
        r"防衛監察",
        r"女性.*平和.*安全保障",
        r"戦略的な安全保障協力",
        r"防衛協力.*交流",
        r"環太平洋合同演習",
        r"災害等対処能力の強化",
        r"ＡＩを活用した戦史史料",
        r"輸送機.*取得$",
        r"機体構成品の取得",
        r"のＰＢＬ$",
        r"法人税について",
    ]),
]

def norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s).strip()

def classify(name: str) -> tuple[int | None, str]:
    n = norm(name)  # NFKC: full-width ASCII → half-width
    for pid, pname, patterns in RULES:
        for pat in patterns:
            # 正規化後・正規化前の両方に対してマッチ（全角ＡＩ→AI 等に対応）
            if re.search(pat, n) or re.search(pat, name):
                return pid, pname
    return None, ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="本番適用（デフォルトはdry-run）")
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, jigyou_name, fiscal_year, source_file "
        "FROM defense_pillar_jigyou WHERE pillar_id=8 ORDER BY id"
    ).fetchall()
    con.close()

    classified: list[tuple[int, str, int, str, str]] = []
    residual:   list[dict]                            = []

    for r in rows:
        pid, pname = classify(r["jigyou_name"])
        if pid:
            classified.append((r["id"], r["jigyou_name"], pid, pname, r["source_file"]))
        else:
            residual.append(dict(r))

    # ── 分類結果サマリ ──
    from collections import Counter
    counts = Counter(pname for _, _, _, pname, _ in classified)
    print("=== 分類結果サマリ ===")
    for pname, cnt in sorted(counts.items()): print(f"  {pname}: {cnt}件")
    print(f"  残留（未分類）: {len(residual)}件")
    print(f"  合計: {len(classified)+len(residual)}件")

    print("\n=== 分類一覧 ===")
    for jid, name, pid, pname, src in classified:
        print(f"  id={jid:4d}  P{pid}({pname})  {name}")

    print("\n=== 残留（手動分類候補） ===")
    for r in residual:
        print(f"  id={r['id']:4d}  FY{r['fiscal_year']}  {r['jigyou_name']}")

    if args.apply:
        print("\n=== 本番適用 ===")
        shutil.copy2(DB, TMP)
        print(f"Backed up: {DB} -> {TMP}")
        con2 = sqlite3.connect(TMP)
        updated = deleted = skipped = 0
        for jid, jname, pid, pname, src in classified:
            try:
                con2.execute(
                    "UPDATE defense_pillar_jigyou SET pillar_id=?, pillar_name=? WHERE id=?",
                    (pid, pname, jid)
                )
                updated += 1
            except sqlite3.IntegrityError:
                # 更新先に同一 (pillar_id, jigyou_name, fiscal_year) が既存 → P8親を削除
                fy = con2.execute(
                    "SELECT fiscal_year FROM defense_pillar_jigyou WHERE id=?", (jid,)
                ).fetchone()[0]
                con2.execute("DELETE FROM defense_pillar_jigyou WHERE id=?", (jid,))
                deleted += 1
                print(f"  DUP→DELETE id={jid} (既存P{pid}に同名 FY{fy} {jname[:30]})")
        con2.commit()
        rem = con2.execute(
            "SELECT COUNT(*) FROM defense_pillar_jigyou WHERE pillar_id=8"
        ).fetchone()[0]
        total_after = con2.execute(
            "SELECT COUNT(*) FROM defense_pillar_jigyou"
        ).fetchone()[0]
        con2.close()
        shutil.copy2(TMP, DB)
        print(f"Updated: {updated}件, Deleted(dup): {deleted}件")
        print(f"P8親残存: {rem}件 / defense_pillar_jigyou総件数: {total_after}件")
        print(f"Copied back: {TMP} -> {DB}")
    else:
        print("\n[dry-run] --apply を付けると本番適用します")


if __name__ == "__main__":
    main()
