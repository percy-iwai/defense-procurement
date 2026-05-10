"""Verify source URLs for all jisseki PDFs and check if H19-H26 exist on ATLA server."""
import requests
import time

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/pdf,*/*",
    "Referer": "https://www.mod.go.jp/atla/souhon/supply/jisseki/index.html",
}

atla_base = "https://www.mod.go.jp/atla/souhon/supply/jisseki/pdf/"

# Test all known filenames on the ATLA server
filenames = [
    "h19_chotatsu_jisseki.pdf",
    "h20_chotatsu_jisseki.pdf",
    "h21_chotatsu_jisseki.pdf",
    "h22_chotatsu_jisseki.pdf",
    "h23_chotatsu_jisseki.pdf",
    "h24_chotatsu_jisseki.pdf",
    "h25_chotatsu_jisseki.pdf",
    "h26_chotatsu_jisseki.pdf",
    "h27_chotatsu_jisseki.pdf",
    "h27_jisseki_mikomi.pdf",
    "h28_chotatsu_jisseki.pdf",
    "h28_jisseki_mikomi.pdf",
    "h29_jisseki_mikomi.pdf",
    "h30_jisseki_mikomi.pdf",
    "r01_jisseki_mikomi.pdf",
    "r02_jisseki_mikomi.pdf",
    "r03_jisseki_r04_mikomi.pdf",
    "r04_jisseki_r05_mikomi.pdf",
    "r05_chotatsu_jisseki.pdf",
    "r06_chotatsu_jisseki.pdf",
    "r07_chotatsu_gairyaku.pdf",  # bonus: R07 outline
]

print(f"{'filename':<40} {'status':<8} {'size':>10} {'content-type'}")
print("-" * 85)
for fname in filenames:
    url = atla_base + fname
    try:
        r = requests.head(url, headers=HEADERS, timeout=15, allow_redirects=True)
        ct = r.headers.get("Content-Type", "?")
        cl = r.headers.get("Content-Length", "-")
        print(f"{fname:<40} {r.status_code:<8} {cl:>10} {ct}")
    except Exception as e:
        print(f"{fname:<40} ERROR: {e}")
    time.sleep(0.3)

# Also check WARP for H27/H28 with specific timestamps when they would have been available
print("\n=== WARP URL attempts for H27/H28 ===")
warp_base = "https://warp.ndl.go.jp"
# Try various WARP formats
warp_urls = [
    # New WARP format (web archive style)
    f"{warp_base}/web/20171001000000/www.mod.go.jp/atla/souhon/supply/jisseki/pdf/h27_chotatsu_jisseki.pdf",
    f"{warp_base}/web/20171001000000/www.mod.go.jp/atla/souhon/supply/jisseki/pdf/h27_jisseki_mikomi.pdf",
    f"{warp_base}/web/20181001000000/www.mod.go.jp/atla/souhon/supply/jisseki/pdf/h28_chotatsu_jisseki.pdf",
    f"{warp_base}/web/20181001000000/www.mod.go.jp/atla/souhon/supply/jisseki/pdf/h28_jisseki_mikomi.pdf",
    f"{warp_base}/web/20190601000000/www.mod.go.jp/atla/souhon/supply/jisseki/pdf/h27_jisseki_mikomi.pdf",
    f"{warp_base}/web/20190601000000/www.mod.go.jp/atla/souhon/supply/jisseki/pdf/h28_jisseki_mikomi.pdf",
    # Old WARP format (info:ndljp)
    f"{warp_base}/info:ndljp/pid/9975652/www.mod.go.jp/atla/souhon/supply/jisseki/pdf/h27_jisseki_mikomi.pdf",
    f"{warp_base}/info:ndljp/pid/9975652/www.mod.go.jp/atla/souhon/supply/jisseki/pdf/h28_jisseki_mikomi.pdf",
]

for url in warp_urls:
    try:
        r = requests.head(url, headers=HEADERS, timeout=15, allow_redirects=True)
        ct = r.headers.get("Content-Type", "?")
        cl = r.headers.get("Content-Length", "-")
        fname = url.split("/")[-1]
        ts = url.split("warp.ndl.go.jp/")[1][:20]
        print(f"{ts}...{fname}: {r.status_code} / {ct[:30]} / {cl}")
    except Exception as e:
        print(f"{url[-60:]}: ERROR {e}")
    time.sleep(0.3)
