"""Preview specific pages of bukai PDFs to understand structure."""
import sys, io
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
import pdfplumber

DRASTIC = Path(r"C:\Users\Percy Iwai\Documents\defense_procurement_2nd\data\raw\drastic")

# Preview bukai_siryo03_01.pdf page 30 (known to have yen-based entries)
for pdf_name, page_range in [
    ("bukai_siryo03_01.pdf", range(28, 33)),
    ("bukai_siryo04_02.pdf", range(4, 8)),
    ("siryo06_02.pdf", range(0, 5)),
]:
    path = DRASTIC / pdf_name
    if not path.exists():
        print(f"MISSING: {pdf_name}")
        continue
    with pdfplumber.open(path) as pdf:
        print(f"\n{'='*70}")
        print(f"{pdf_name}: {len(pdf.pages)} pages total")
        for i in page_range:
            if i >= len(pdf.pages):
                break
            text = pdf.pages[i].extract_text() or ""
            print(f"\n--- Page {i+1} ---")
            print(text[:800])
