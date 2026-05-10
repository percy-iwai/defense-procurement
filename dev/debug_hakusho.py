"""Debug hakusho HTML structure and find the right URL."""
import sys, re, requests
sys.stdout.reconfigure(encoding='utf-8')

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36")

# FY2023 URL that worked (200 OK)
url = "http://www.clearing.mod.go.jp/hakusho_data/2023/html/n230103000.html"
r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
print(f"Status: {r.status_code}")
print(f"Content-Type: {r.headers.get('content-type', '')}")
print(f"Content len: {len(r.content)}")

# Try different encodings
for enc in ("utf-8", "shift_jis", "euc-jp"):
    try:
        text = r.content.decode(enc, errors="strict")
        print(f"Encoding: {enc}")
        break
    except:
        pass
else:
    text = r.content.decode("utf-8", errors="replace")
    print("Encoding: utf-8 fallback")

print("\n--- First 2000 chars ---")
print(text[:2000])

# Check if it has any 7-pillar keywords
pillars = ["スタンド・オフ", "統合防空", "無人アセット", "領域横断", "指揮統制", "機動展開", "持続性"]
for p in pillars:
    count = text.count(p)
    if count > 0:
        print(f"\nFound '{p}' {count} times")

# Try to get the index page to find all html files
print("\n--- Checking index ---")
idx_url = "http://www.clearing.mod.go.jp/hakusho_data/2023/html/"
try:
    r2 = requests.get(idx_url, headers={"User-Agent": UA}, timeout=30)
    print(f"Index status: {r2.status_code}")
    if r2.status_code == 200:
        idx_text = r2.content.decode("shift_jis", errors="replace")
        # Find html links
        links = re.findall(r'href="([^"]+\.html)"', idx_text)
        print(f"HTML files in index: {len(links)}")
        for link in links[:20]:
            print(f"  {link}")
except Exception as e:
    print(f"Index error: {e}")
