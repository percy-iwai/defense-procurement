"""Check j/procurement/ page content with proper encoding."""
import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,*/*",
}

r = requests.get("https://www.mod.go.jp/j/procurement/", headers=HEADERS, timeout=20)
print(f"Status: {r.status_code}")
print(f"Encoding: {r.encoding}")
print(f"Content-Type: {r.headers.get('Content-Type')}")
print(f"Length: {len(r.content)}")
# Try different encodings
for enc in ["utf-8", "shift_jis", "euc_jp", "latin1"]:
    try:
        text = r.content.decode(enc)
        print(f"\n=== {enc} ===")
        print(text[:500])
        break
    except Exception as e:
        print(f"  {enc}: {e}")

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
r2 = requests.get("https://www.mod.go.jp/j/procurement/", headers=HEADERS, timeout=20)
r2.encoding = "utf-8"
print(f"\n=== force utf-8 ===")
print(r2.text[:1000])
