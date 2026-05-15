"""Verify R06 PDF content."""
import pdfplumber, re, sys

fpath = r"C:\Users\Percy Iwai\Documents\defense_procurement_2nd\data\raw\chuou_chotatsu_jisseki\r06_chotatsu_jisseki.pdf"
sys.stdout = open("dev/r06_check.txt", "w", encoding="utf-8")
with pdfplumber.open(fpath) as pdf:
    print(f"Pages: {len(pdf.pages)}")
    for i, page in enumerate(pdf.pages[:4]):
        t = page.extract_text() or ""
        print(f"\n--- Page {i+1} ---")
        print(t[:1000])
sys.stdout.close()
sys.stdout = sys.__stdout__
print("Done.")
