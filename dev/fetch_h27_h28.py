"""Try to find H27/H28 jisseki PDFs via ATLA index page and URL patterns."""
import requests
import time
import re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/pdf,*/*",
    "Accept-Language": "ja,en;q=0.9",
}

save_dir = r"C:\Users\Percy Iwai\Documents\defense_procurement_2nd\data\raw\chuou_chotatsu_jisseki"

# Try to access ATLA index via different referrers
print("=== Trying ATLA index page ===")
for url in [
    "https://www.mod.go.jp/atla/souhon/supply/jisseki/index.html",
    "https://www.mod.go.jp/atla/choutatsuchuuou.html",
]:
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        print(f"{url}: {r.status_code} ({len(r.content)} bytes)")
        if r.status_code == 200:
            # Find all PDF links
            pdfs = re.findall(r'href="([^"]*jisseki[^"]*\.pdf)"', r.text)
            pdfs += re.findall(r'href="([^"]*h2[0-9][^"]*\.pdf)"', r.text)
            if pdfs:
                print(f"  Found PDFs: {pdfs}")
            # Print raw HTML excerpt
            excerpt = r.text[:2000]
            print(f"  HTML excerpt: {excerpt[:500]}")
    except Exception as e:
        print(f"  ERROR: {e}")
    time.sleep(1)

# Try URL patterns
print("\n=== Trying URL patterns ===")
import os
base_url = "https://www.mod.go.jp/atla/souhon/supply/jisseki/pdf/"
candidates = [
    "h27_jisseki_mikomi.pdf",
    "h28_jisseki_mikomi.pdf",
    "h27_chotatsu_jisseki.pdf",
    "h28_chotatsu_jisseki.pdf",
    "h27h28_jisseki_mikomi.pdf",
    "h27_h28_jisseki_mikomi.pdf",
    "h27_jisseki.pdf",
    "h28_jisseki.pdf",
    "H27_jisseki_mikomi.pdf",
    "H28_jisseki_mikomi.pdf",
]
for fname in candidates:
    url = base_url + fname
    try:
        r = requests.head(url, headers=HEADERS, timeout=15, allow_redirects=True)
        print(f"{fname}: {r.status_code}")
        if r.status_code == 200:
            # Download it
            r2 = requests.get(url, headers=HEADERS, timeout=30)
            fpath = os.path.join(save_dir, fname)
            with open(fpath, "wb") as f:
                f.write(r2.content)
            print(f"  -> SAVED!")
    except Exception as e:
        print(f"{fname}: ERROR {e}")
    time.sleep(0.5)

# WARP attempts
print("\n=== Trying WARP ===")
warp_patterns = [
    # Try WARP with different timestamps for H28 data (published ~2017-2018)
    "https://warp.ndl.go.jp/web/20181001000000/www.mod.go.jp/atla/souhon/supply/jisseki/index.html",
    "https://warp.ndl.go.jp/web/20190101000000/www.mod.go.jp/atla/souhon/supply/jisseki/index.html",
    "https://warp.ndl.go.jp/web/20200101000000/www.mod.go.jp/atla/souhon/supply/jisseki/index.html",
]
for url in warp_patterns:
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        print(f"{url[:80]}: {r.status_code}")
        if r.status_code == 200 and "jisseki" in r.text.lower():
            pdfs = re.findall(r'(h2[678]_[^"<\s]+\.pdf)', r.text, re.IGNORECASE)
            print(f"  Found relevant PDFs: {pdfs}")
            print(f"  Text excerpt: {r.text[:1000]}")
    except Exception as e:
        print(f"  ERROR: {e}")
    time.sleep(1)
