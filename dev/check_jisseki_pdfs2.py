"""Check PDF contents with UTF-8 output file."""
import pdfplumber
import re
import os
import sys

sys.stdout = open("dev/pdf_check_result.txt", "w", encoding="utf-8")

def extract_year_info(text):
    reiwa = re.findall(r"令和\s*(\d+|元)\s*年度", text)
    heisei = re.findall(r"平成\s*(\d+)\s*年度", text)
    jisseki = "実績" in text
    mikomi = "見込み" in text or "見込" in text
    return reiwa, heisei, jisseki, mikomi

def process_dir(dirpath, label):
    print(f"\n=== {label} ===")
    files = sorted(f for f in os.listdir(dirpath) if f.endswith(".pdf"))
    for fname in files:
        fpath = os.path.join(dirpath, fname)
        try:
            with pdfplumber.open(fpath) as pdf:
                text = ""
                for page in pdf.pages[:4]:
                    t = page.extract_text() or ""
                    text += t + "\n"
            reiwa, heisei, jisseki, mikomi = extract_year_info(text)
            reiwa_str = ",".join(sorted(set(reiwa))) if reiwa else "-"
            # Sort heisei by numeric value
            heisei_unique = sorted(set(heisei), key=lambda x: int(x))
            heisei_str = ",".join(heisei_unique) if heisei_unique else "-"
            print(f"\nFILE: {fname}")
            print(f"  平成年度: {heisei_str}")
            print(f"  令和年度: {reiwa_str}")
            print(f"  実績: {jisseki}, 見込: {mikomi}")
            snippet = text[:600].replace("\n", " / ").strip()
            print(f"  テキスト抜粋: {snippet[:500]}")
        except Exception as e:
            print(f"FILE: {fname} -> ERROR: {e}")

base = r"C:\Users\Percy Iwai\Documents\defense_procurement_2nd\data\raw"
process_dir(os.path.join(base, "chuou_chotatsu_jisseki"), "中央調達実績 (jisseki)")
process_dir(os.path.join(base, "chuou_chotatsu_gaikyo"), "中央調達概況 (gaikyo)")
sys.stdout.close()
sys.stdout = sys.__stdout__
print("Done. See dev/pdf_check_result.txt")
