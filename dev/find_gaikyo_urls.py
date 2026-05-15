"""Find source URLs for gaikyo PDFs on ATLA site."""
import requests, time

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "*/*",
}
base_atla = "https://www.mod.go.jp/atla/souhon/supply/jisseki/"

gaikyo_candidates = [
    # Direct paths under jisseki
    "pdf/r02_chuou_chotatsu_gaikyo.pdf",
    "pdf/r03_chuou_chotatsu_gaikyo.pdf",
    "pdf/r04_chuou_chotatsu_gaikyo.pdf",
    "pdf/r05_chuou_chotatsu_gaikyo.pdf",
    # Alternative paths
    "gaikyo/pdf/r02_chuou_chotatsu_gaikyo.pdf",
    "gaikyo/r02_chuou_chotatsu_gaikyo.pdf",
    "chuou/r02_chuou_chotatsu_gaikyo.pdf",
]

print("=== ATLA jisseki gaikyo paths ===")
for p in gaikyo_candidates:
    url = base_atla + p
    try:
        r = requests.head(url, headers=HEADERS, timeout=10, allow_redirects=True)
        ct = r.headers.get("Content-Type","?")
        cl = r.headers.get("Content-Length","-")
        print(f"{p}: {r.status_code} / {ct[:30]} / {cl}")
    except Exception as e:
        print(f"{p}: ERROR {e}")
    time.sleep(0.3)

# Also check gaikyo index page
print("\n=== Gaikyo index candidates ===")
for url in [
    "https://www.mod.go.jp/atla/souhon/supply/jisseki/gaikyo.html",
    "https://www.mod.go.jp/atla/souhon/supply/jisseki/chuou.html",
]:
    try:
        r = requests.head(url, headers=HEADERS, timeout=10)
        print(f"{url}: {r.status_code}")
    except Exception as e:
        print(f"{url}: {e}")

# The ATLA index shows r07_chotatsu_gairyaku.pdf - check if similar exists for r02-r06
print("\n=== r## gairyaku files ===")
for fy in ["r02","r03","r04","r05","r06","r07"]:
    for suffix in ["_chuou_chotatsu_gaikyo.pdf", "_chotatsu_gaikyo.pdf", "_chotatsu_gairyaku.pdf"]:
        url = f"https://www.mod.go.jp/atla/souhon/supply/jisseki/pdf/{fy}{suffix}"
        try:
            r = requests.head(url, headers=HEADERS, timeout=8, allow_redirects=True)
            ct = r.headers.get("Content-Type","?")
            cl = r.headers.get("Content-Length","-")
            if r.status_code == 200:
                print(f"FOUND: {fy}{suffix}: {r.status_code} / {ct} / {cl}")
            else:
                print(f"{fy}{suffix}: {r.status_code}")
        except Exception as e:
            print(f"{fy}{suffix}: ERROR {e}")
        time.sleep(0.2)
