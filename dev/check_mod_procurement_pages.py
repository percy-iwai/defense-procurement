"""Check mod.go.jp/j/procurement/ and related old paths for H19-H26 PDFs."""
import requests
from bs4 import BeautifulSoup
import re, time

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,*/*",
}

urls_to_check = [
    "https://www.mod.go.jp/j/procurement/",
    "https://www.mod.go.jp/j/approach/hyouka/jisseki/",
    "https://www.mod.go.jp/j/approach/zaim/",
    # Old DFAB paths (装備施設本部)
    "https://www.mod.go.jp/j/procurement/jisseki/",
    "https://www.mod.go.jp/j/procurement/index.html",
]

for url in urls_to_check:
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.encoding = "utf-8"
        print(f"\n{url}: {r.status_code} ({len(r.content)} bytes)")
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            # Find all links
            links = soup.find_all("a", href=True)
            pdf_links = [a["href"] for a in links if ".pdf" in a["href"].lower()]
            if pdf_links:
                print(f"  PDFs: {pdf_links[:10]}")
            all_links = [(a.get_text(strip=True)[:40], a["href"]) for a in links[:20]]
            print(f"  Links: {all_links[:10]}")
            text = soup.get_text()[:500]
            print(f"  Text: {text[:300]}")
    except Exception as e:
        print(f"{url}: ERROR {e}")
    time.sleep(0.5)

# Also check the WARP's API for resource listings
print("\n=== Checking WARP API for mod.go.jp ATLA jisseki ===")
warp_api_url = "https://warp.ndl.go.jp/api/timemap?url=https://www.mod.go.jp/atla/souhon/supply/jisseki/pdf/h29_jisseki_mikomi.pdf"
try:
    r = requests.get(warp_api_url, headers=HEADERS, timeout=20)
    print(f"WARP API h29: {r.status_code}")
    if r.status_code == 200:
        print(f"  {r.text[:500]}")
except Exception as e:
    print(f"WARP API h29: ERROR {e}")

# CDX API (Wayback Machine compatible)
cdx_url = "http://web.archive.org/cdx/search/cdx?url=www.mod.go.jp/atla/souhon/supply/jisseki/pdf/*.pdf&output=text&limit=30"
try:
    r = requests.get(cdx_url, headers=HEADERS, timeout=20)
    print(f"\nCDX API: {r.status_code}")
    if r.status_code == 200:
        print(r.text[:2000])
except Exception as e:
    print(f"CDX API: {e}")
