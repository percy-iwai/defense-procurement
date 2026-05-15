"""Try to find the original source URLs for H19-H26 jisseki PDFs (old DFAB/MOD paths)."""
import requests
import time

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "*/*",
}

# Old MOD paths for procurement/DFAB pages
# The old 装備施設本部 (DFAB) was at various paths under mod.go.jp
old_paths = [
    # Possible old paths for DFAB procurement stats
    "https://www.mod.go.jp/j/approach/procurement/",
    "https://www.mod.go.jp/j/procurement/",
    "https://www.mod.go.jp/atla/souhon/jisseki/",
    "https://www.mod.go.jp/atla/jisseki/",
]

print("=== Checking possible old index paths ===")
for path in old_paths:
    try:
        r = requests.head(path, headers=HEADERS, timeout=10, allow_redirects=True)
        print(f"{path}: {r.status_code}")
    except Exception as e:
        print(f"{path}: {e}")
    time.sleep(0.3)

# Try WARP archive of old ATLA jisseki index from 2016-2018
# when H19-H26 might still have been listed
print("\n=== WARP: ATLA jisseki index from 2016-2018 ===")
warp_index_urls = [
    "https://warp.ndl.go.jp/web/20160601000000/www.mod.go.jp/atla/souhon/supply/jisseki/index.html",
    "https://warp.ndl.go.jp/web/20170601000000/www.mod.go.jp/atla/souhon/supply/jisseki/index.html",
    "https://warp.ndl.go.jp/web/20180601000000/www.mod.go.jp/atla/souhon/supply/jisseki/index.html",
    "https://warp.ndl.go.jp/web/20200601000000/www.mod.go.jp/atla/souhon/supply/jisseki/index.html",
]

import re
for url in warp_index_urls:
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        print(f"\n{url[-60:]}: {r.status_code} ({len(r.content)} bytes)")
        if r.status_code == 200:
            # Look for PDF links
            pdfs = re.findall(r'href="([^"]*\.pdf)"', r.text, re.IGNORECASE)
            pdfs2 = re.findall(r'href=\'([^\']*\.pdf)\'', r.text, re.IGNORECASE)
            all_pdfs = pdfs + pdfs2
            if all_pdfs:
                print(f"  PDF links: {all_pdfs}")
            else:
                # Print some of the text to see what's on the page
                txt = r.text[:2000].replace("\n", " ")
                print(f"  Page text snippet: {txt[:500]}")
    except Exception as e:
        print(f"{url[-60:]}: ERROR {e}")
    time.sleep(1)

# Try WARP for H26 and H29 with year-appropriate timestamps
# H26 jisseki would have been published ~2015-2016
print("\n=== WARP: H26 and H29 PDF direct access ===")
warp_pdfs = [
    # H26 might be on old MOD path (before ATLA)
    "https://warp.ndl.go.jp/web/20160101000000/www.mod.go.jp/atla/souhon/supply/jisseki/pdf/h26_chotatsu_jisseki.pdf",
    # H29 was published when ATLA was already running (2018)
    "https://warp.ndl.go.jp/web/20180901000000/www.mod.go.jp/atla/souhon/supply/jisseki/pdf/h29_jisseki_mikomi.pdf",
    "https://warp.ndl.go.jp/web/20190901000000/www.mod.go.jp/atla/souhon/supply/jisseki/pdf/h29_jisseki_mikomi.pdf",
    "https://warp.ndl.go.jp/web/20191001000000/www.mod.go.jp/atla/souhon/supply/jisseki/pdf/h30_jisseki_mikomi.pdf",
]

for url in warp_pdfs:
    try:
        r = requests.head(url, headers=HEADERS, timeout=15, allow_redirects=True)
        ct = r.headers.get("Content-Type","?")
        cl = r.headers.get("Content-Length","-")
        fname = url.split("/")[-1]
        ts = url.split("warp.ndl.go.jp/")[1][:20]
        print(f"{ts}.../{fname}: {r.status_code} / {ct[:30]} / {cl}bytes")
    except Exception as e:
        print(f"ERROR: {e}")
    time.sleep(0.5)
