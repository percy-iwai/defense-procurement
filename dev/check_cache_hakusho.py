"""Check if hakusho pages are cached, and preview the first PDF structure."""
import sys, hashlib
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

ROOT = Path(r"C:\Users\Percy Iwai\Documents\defense_procurement_2nd")
sys.path.insert(0, str(ROOT))
from collectors.http_client import fetch

CACHE_DIR = ROOT / "data" / "raw" / "_cache"

def cache_path(url, ext=""):
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return CACHE_DIR / f"{h}{ext}"

# Check hakusho cache
years = [2022, 2023, 2024, 2025]
for yr in years:
    url = f"https://www.clearing.mod.go.jp/hakusho_data/{yr}/html/n240103000.html"
    cp = cache_path(url, ".html")
    exists = cp.exists()
    print(f"  FY{yr} cache: {cp.name} exists={exists}")
    if not exists:
        # try without extension
        cp2 = cache_path(url, "")
        print(f"         no-ext: {cp2.name} exists={cp2.exists()}")

# Also check for bukai PDF cache
bukai_base = "https://www.mod.go.jp/j/policy/agenda/meeting/drastic-reinforcement/pdf/"
test_pdfs = ["siryo01_01.pdf", "siryo06_02.pdf", "siryo07_01.pdf"]
print("\n--- Bukai PDF cache check ---")
for pdf in test_pdfs:
    url = bukai_base + pdf
    cp = cache_path(url, ".pdf")
    exists = cp.exists()
    print(f"  {pdf}: {cp.name} exists={exists}")

# Try fetching one bukai PDF to check structure
print("\n--- Fetching siryo07_01.pdf preview ---")
url = bukai_base + "siryo07_01.pdf"
data = fetch(url)
if data:
    print(f"  Size: {len(data)} bytes")
    import pdfplumber, io
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        print(f"  Pages: {len(pdf.pages)}")
        for i, p in enumerate(pdf.pages[:3]):
            text = p.extract_text() or ""
            print(f"\n  === Page {i+1} ===")
            print(text[:500])
else:
    print("  FAILED")
