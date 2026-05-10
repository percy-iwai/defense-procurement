"""Try to download missing jisseki PDFs: H27, H28, R06."""
import requests
import os
import time

save_dir = r"C:\Users\Percy Iwai\Documents\defense_procurement_2nd\data\raw\chuou_chotatsu_jisseki"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/pdf,*/*",
    "Accept-Language": "ja,en;q=0.9",
    "Referer": "https://www.mod.go.jp/atla/souhon/supply/jisseki/index.html",
}

# Candidate URLs to try
CANDIDATES = [
    # R06 実績
    ("r06_chotatsu_jisseki.pdf", "https://www.mod.go.jp/atla/souhon/supply/jisseki/pdf/r06_chotatsu_jisseki.pdf"),
    # H27 (ATLA established Oct 2015)
    ("h27_jisseki_mikomi.pdf", "https://www.mod.go.jp/atla/souhon/supply/jisseki/pdf/h27_jisseki_mikomi.pdf"),
    ("h27_chotatsu_jisseki.pdf", "https://www.mod.go.jp/atla/souhon/supply/jisseki/pdf/h27_chotatsu_jisseki.pdf"),
    # H28
    ("h28_jisseki_mikomi.pdf", "https://www.mod.go.jp/atla/souhon/supply/jisseki/pdf/h28_jisseki_mikomi.pdf"),
    ("h28_chotatsu_jisseki.pdf", "https://www.mod.go.jp/atla/souhon/supply/jisseki/pdf/h28_chotatsu_jisseki.pdf"),
]

for fname, url in CANDIDATES:
    fpath = os.path.join(save_dir, fname)
    if os.path.exists(fpath):
        print(f"SKIP (exists): {fname}")
        continue
    print(f"Trying: {url}")
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        print(f"  Status: {r.status_code}, Content-Type: {r.headers.get('Content-Type','?')}, Size: {len(r.content)} bytes")
        if r.status_code == 200 and b"%PDF" in r.content[:10]:
            with open(fpath, "wb") as f:
                f.write(r.content)
            print(f"  -> SAVED: {fname}")
        else:
            print(f"  -> SKIP: not a valid PDF")
    except Exception as e:
        print(f"  -> ERROR: {e}")
    time.sleep(1)

print("\nDone.")
