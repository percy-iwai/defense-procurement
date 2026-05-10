"""Preview bukai PDF pages to understand project listing structure."""
import sys, io
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

ROOT = Path(r"C:\Users\Percy Iwai\Documents\defense_procurement_2nd")
sys.path.insert(0, str(ROOT))
from collectors.http_client import fetch
import pdfplumber

BUKAI_BASE = "https://www.mod.go.jp/j/policy/agenda/meeting/drastic-reinforcement/pdf/"

# Check siryo06_02.pdf (known to have entries in bukai)
pdfs_to_check = ["siryo06_02.pdf", "siryo05_02.pdf", "siryo04_01.pdf"]
for pdf_name in pdfs_to_check:
    url = BUKAI_BASE + pdf_name
    data = fetch(url)
    if not data:
        print(f"FAILED: {pdf_name}")
        continue
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        total_pages = len(pdf.pages)
        print(f"\n{'='*60}")
        print(f"{pdf_name}: {total_pages} pages, {len(data)//1024}KB")

        # Show pages 1-5 to find structure
        for i, page in enumerate(pdf.pages[:8]):
            text = page.extract_text() or ""
            if not text.strip():
                continue
            # Look for pillar keywords
            has_pillar = any(k in text for k in [
                "スタンド・オフ", "統合防空", "無人アセット", "領域横断",
                "指揮統制", "機動展開", "持続性", "主な事業", "主要事業"
            ])
            print(f"\n--- Page {i+1} {'[PILLAR/PROJECT]' if has_pillar else ''} ---")
            print(text[:600])
