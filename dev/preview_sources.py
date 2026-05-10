"""Preview bukai parent page and hakusho HTML to understand structure."""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import re
from pathlib import Path

ROOT = Path(r"C:\Users\Percy Iwai\Documents\defense_procurement_2nd")
sys.path.insert(0, str(ROOT))
from collectors.http_client import fetch

# ── A: Bukai parent page ──────────────────────────────────────────────────
print("=== A: Bukai parent page ===")
BUKAI_INDEX = "https://www.mod.go.jp/j/policy/agenda/meeting/drastic-reinforcement/"
data = fetch(BUKAI_INDEX)
if data:
    text = data.decode("utf-8", errors="replace")
    print(f"Page size: {len(text)} chars")
    # Find PDF links
    pdf_links = re.findall(r'href="([^"]+\.pdf[^"]*)"', text, re.IGNORECASE)
    print(f"PDF links found: {len(pdf_links)}")
    for link in pdf_links[:30]:
        print(f"  {link}")
    if len(pdf_links) > 30:
        print(f"  ... and {len(pdf_links)-30} more")
else:
    print("  FAILED to fetch")

# ── B: Hakusho HTML (one year to preview) ────────────────────────────────
print("\n=== B: Hakusho HTML FY2024 preview ===")
HAK_URL = "https://www.clearing.mod.go.jp/hakusho_data/2024/html/n240103000.html"
data = fetch(HAK_URL)
if data:
    # Try different encodings
    for enc in ("utf-8", "shift_jis", "euc-jp"):
        try:
            text = data.decode(enc, errors="strict")
            print(f"Encoding: {enc}, size={len(text)}")
            break
        except UnicodeDecodeError:
            pass
    else:
        text = data.decode("utf-8", errors="replace")
        print(f"Encoding: utf-8(fallback), size={len(text)}")

    # Show first 3000 chars
    print("--- first 3000 chars ---")
    print(text[:3000])
else:
    print("  FAILED to fetch")
