"""Check ATLA website for gaikyo publication section."""
import requests
from bs4 import BeautifulSoup
import time

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "*/*",
}

# Check the ATLA main procurement page for gaikyo links
for url in [
    "https://www.mod.go.jp/atla/choutatsuchuuou.html",
    "https://www.mod.go.jp/atla/souhon/index.html",
]:
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        print(f"\n{url}: {r.status_code}")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(strip=True)
            if text or "pdf" in href.lower():
                print(f"  [{text[:50]}] -> {href}")
    except Exception as e:
        print(f"{url}: ERROR {e}")
    time.sleep(0.5)

# Try different gaikyo URL patterns on ATLA
import re
candidates = []
for fy in ["r01","r02","r03","r04","r05","r06"]:
    for pattern in [
        f"souhon/gaikyo/{fy}.pdf",
        f"souhon/gaikyo/{fy}_gaikyo.pdf",
        f"souhon/gaikyo/pdf/{fy}_chuou_chotatsu_gaikyo.pdf",
        f"choutatsuchuuou/gaikyo/{fy}.pdf",
        f"choutatsuchuuou/{fy}_gaikyo.pdf",
    ]:
        candidates.append(f"https://www.mod.go.jp/atla/{pattern}")

print("\n=== Testing gaikyo URL patterns ===")
for url in candidates:
    try:
        r = requests.head(url, headers=HEADERS, timeout=8, allow_redirects=True)
        if r.status_code == 200:
            print(f"FOUND! {url}: {r.status_code}")
    except:
        pass
    time.sleep(0.1)

print("Done searching gaikyo patterns.")
