"""
Match equipment_master entries to candidate URLs from cached MoD HTML.
"""
import sys, io, json, sqlite3, re, unicodedata
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

with open("temp/mod_equipment/_candidates.json", "r", encoding="utf-8") as f:
    candidates = json.load(f)


def nfkc(s):
    return unicodedata.normalize("NFKC", s) if s else ""


def norm_strict(s):
    s = nfkc(s).lower()
    return re.sub(r"[\s/・／,，、　()（）「」\[\]【】\-_.]", "", s)


def url_path_tail(url):
    parts = [p for p in url.rstrip("/").split("/") if p][-2:]
    return [p.lower() for p in parts]


# Manual overrides (unambiguous direct matches verified by hand)
MANUAL = {
    # ASDF specific direct mappings
    ("ASDF", "asdf_f35a"):     "https://www.mod.go.jp/asdf/equipment/sentouki/F-35/",
    ("ASDF", "asdf_f15jdj"):   "https://www.mod.go.jp/asdf/equipment/sentouki/F-15/",
    ("ASDF", "asdf_f2ab"):     "https://www.mod.go.jp/asdf/equipment/sentouki/F-2/",
    ("ASDF", "asdf_e2c"):      "https://www.mod.go.jp/asdf/equipment/keikaiki/E-2C/",
    ("ASDF", "asdf_e2d"):      "https://www.mod.go.jp/asdf/equipment/keikaiki/E-2C/",
    ("ASDF", "asdf_e767"):     "https://www.mod.go.jp/asdf/equipment/keikaiki/E-767/",
    ("ASDF", "asdf_c1"):       "https://www.mod.go.jp/asdf/equipment/yusouki/C-1/",
    ("ASDF", "asdf_c2"):       "https://www.mod.go.jp/asdf/equipment/yusouki/C-2/",
    ("ASDF", "asdf_c130h"):    "https://www.mod.go.jp/asdf/equipment/yusouki/C-130H/",
    ("ASDF", "asdf_kc767"):    "https://www.mod.go.jp/asdf/equipment/yusouki/KC-767/",
    ("ASDF", "asdf_kc46a"):    "https://www.mod.go.jp/asdf/equipment/kc-46a.html",
    ("ASDF", "asdf_kc130h"):   "https://www.mod.go.jp/asdf/equipment/yusouki/C-130H/",
    ("ASDF", "asdf_ch47j"):    "https://www.mod.go.jp/asdf/equipment/yusouki/CH-47J/",
    ("ASDF", "asdf_uh60j"):    "https://www.mod.go.jp/asdf/equipment/kyuunanki/UH-60J/",
    ("ASDF", "asdf_rq4b"):     "https://www.mod.go.jp/asdf/equipment/globalhawk/RQ-4B_Globalhawk/",
    ("ASDF", "asdf_pac3"):     "https://www.mod.go.jp/asdf/equipment/other/Patriot/",
    ("ASDF", "asdf_basic_sam"):"https://www.mod.go.jp/asdf/equipment/other/yuudoudan/",

    # GSDF aircraft on /air/ page
    ("GSDF", "gsdf_uh1j"):     "https://www.mod.go.jp/gsdf/equipment/air/",
    ("GSDF", "gsdf_uh2"):      "https://www.mod.go.jp/gsdf/equipment/air/",
    ("GSDF", "gsdf_uh60ja"):   "https://www.mod.go.jp/gsdf/equipment/air/",
    ("GSDF", "gsdf_ah1s"):     "https://www.mod.go.jp/gsdf/equipment/air/",
    ("GSDF", "gsdf_ah64d"):    "https://www.mod.go.jp/gsdf/equipment/air/",
    ("GSDF", "gsdf_oh1"):      "https://www.mod.go.jp/gsdf/equipment/air/",
    ("GSDF", "gsdf_ch47jja"):  "https://www.mod.go.jp/gsdf/equipment/air/",
    ("GSDF", "gsdf_lr2"):      "https://www.mod.go.jp/gsdf/equipment/air/",
    ("GSDF", "gsdf_v22"):      "https://www.mod.go.jp/gsdf/equipment/air/",
    ("GSDF", "gsdf_cat_combat_aircraft"): "https://www.mod.go.jp/gsdf/equipment/air/",

    # GSDF guns/ammo/missiles on /fire/
    ("GSDF", "gsdf_20rifle"):           "https://www.mod.go.jp/gsdf/equipment/fire/",
    ("GSDF", "gsdf_91sam"):             "https://www.mod.go.jp/gsdf/equipment/fire/",
    ("GSDF", "gsdf_03sam_kai"):         "https://www.mod.go.jp/gsdf/equipment/fire/",
    ("GSDF", "gsdf_11sam"):             "https://www.mod.go.jp/gsdf/equipment/fire/",
    ("GSDF", "gsdf_12ssm_kai"):         "https://www.mod.go.jp/gsdf/equipment/fire/",
    ("GSDF", "gsdf_hgv"):               "https://www.mod.go.jp/gsdf/equipment/fire/",
    ("GSDF", "gsdf_cat_arty"):          "https://www.mod.go.jp/gsdf/equipment/fire/",
    ("GSDF", "gsdf_cat_heavy_mortar"):  "https://www.mod.go.jp/gsdf/equipment/fire/",
    ("GSDF", "gsdf_cat_portable_sam"):  "https://www.mod.go.jp/gsdf/equipment/fire/",
    ("GSDF", "gsdf_cat_ssm_regiment"):  "https://www.mod.go.jp/gsdf/equipment/fire/",

    # GSDF vehicles
    ("GSDF", "gsdf_cat_tank"):    "https://www.mod.go.jp/gsdf/equipment/ve/",
    ("GSDF", "gsdf_cat_armored"): "https://www.mod.go.jp/gsdf/equipment/ve/",

    # GSDF C/E
    ("GSDF", "gsdf_wbml_radio"):  "https://www.mod.go.jp/gsdf/equipment/ce/",
    ("GSDF", "gsdf_yagai_comm"):  "https://www.mod.go.jp/gsdf/equipment/ce/",

    # MSDF fixed-wing aircraft
    ("MSDF", "msdf_p1"):     "https://www.mod.go.jp/msdf/equipment/aircraft/patrol/p-1/",
    ("MSDF", "msdf_p3c"):    "https://www.mod.go.jp/msdf/equipment/aircraft/patrol/p-3c/",
    ("MSDF", "msdf_us2"):    "https://www.mod.go.jp/msdf/equipment/aircraft/rescue/us-2/",

    # MSDF rotorcraft
    ("MSDF", "msdf_sh60j"):  "https://www.mod.go.jp/msdf/equipment/rotorcraft/patrol/sh60j/",
    ("MSDF", "msdf_sh60k"):  "https://www.mod.go.jp/msdf/equipment/rotorcraft/patrol/sh60k/",
    ("MSDF", "msdf_sh60l"):  "https://www.mod.go.jp/msdf/equipment/rotorcraft/patrol/sh60k/",
    ("MSDF", "msdf_mch101"): "https://www.mod.go.jp/msdf/equipment/rotorcraft/ms-t/mch-101/",

    # MSDF ship-class categories
    ("MSDF", "msdf_cat_destroyer"):    "https://www.mod.go.jp/msdf/equipment/ships/",
    ("MSDF", "msdf_cat_submarine"):    "https://www.mod.go.jp/msdf/equipment/ships/index3.html",
    ("MSDF", "msdf_cat_mine_warfare"): "https://www.mod.go.jp/msdf/equipment/ships/",
    ("MSDF", "msdf_cat_patrol"):       "https://www.mod.go.jp/msdf/equipment/ships/",
    ("MSDF", "msdf_cat_transport"):    "https://www.mod.go.jp/msdf/equipment/ships/",
    ("MSDF", "msdf_cat_auxiliary"):    "https://www.mod.go.jp/msdf/equipment/ships/index2.html",
    ("MSDF", "msdf_aegis_ship"):       "https://www.mod.go.jp/msdf/equipment/ships/ddg/atago/",
}


def find_url(eq_id, name_ja, name_en, branch, category):
    if (branch, eq_id) in MANUAL:
        return MANUAL[(branch, eq_id)], "manual"

    name_norm = norm_strict(name_ja)
    tokens_in_name = []
    if name_en:
        tokens_in_name.append(norm_strict(name_en))
    for m in re.findall(r"[（(]([^）)]+)[）)]", nfkc(name_ja)):
        tokens_in_name.append(norm_strict(m))
    tokens_in_name.append(name_norm)

    best = None
    best_score = 0
    for c in candidates:
        if c["branch"] != branch:
            continue
        for tail in url_path_tail(c["url"]):
            tail_norm = re.sub(r"[\s\-_.]", "", tail.lower())
            for tok in tokens_in_name:
                if not tok or len(tok) < 2:
                    continue
                if tok == tail_norm and 4 > best_score:
                    best, best_score = c, 4
                elif len(tok) >= 3 and tok in tail_norm and 3 > best_score:
                    best, best_score = c, 3
                elif len(tail_norm) >= 3 and tail_norm in tok and 2 > best_score:
                    best, best_score = c, 2
        c_norm = c["norm"]
        for tok in tokens_in_name:
            if not tok or len(tok) < 3:
                continue
            if tok == c_norm and 4 > best_score:
                best, best_score = c, 4
            elif (tok in c_norm or c_norm in tok) and 1 > best_score:
                short_len = min(len(tok), len(c_norm))
                if short_len >= 3:
                    best, best_score = c, 1
    if best:
        return best["url"], f"auto_score{best_score}"
    return None, "no_match"


conn = sqlite3.connect("C:/Users/Percy Iwai/Documents/defense_procurement_2nd/data/db/procurement.db")
cur = conn.cursor()
rows = cur.execute(
    "SELECT equipment_id, name_ja, name_en, branch, category FROM equipment_master ORDER BY branch, category, name_ja"
).fetchall()

results = []
for eq_id, name_ja, name_en, branch, category in rows:
    url, why = find_url(eq_id, name_ja, name_en, branch, category)
    results.append({
        "equipment_id": eq_id,
        "name_ja": name_ja,
        "name_en": name_en,
        "branch": branch,
        "category": category,
        "ref_url_official": url,
        "match_reason": why,
    })

matched = sum(1 for r in results if r["ref_url_official"])
print(f"Matched: {matched}/{len(results)}\n")
print("=== UNMATCHED ===")
for r in results:
    if not r["ref_url_official"]:
        print(f"  {r['branch']}/{r['equipment_id']}: {r['name_ja']}  [{r['category']}]")

print("\n=== MATCHED ===")
for r in results:
    if r["ref_url_official"]:
        print(f"  {r['branch']}/{r['equipment_id']}: {r['name_ja'][:30]:<30} -> {r['ref_url_official']}  ({r['match_reason']})")

with open("temp/mod_equipment/_matches.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
