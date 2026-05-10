"""
yosan_fy2025.pdf の7ページ目（0-indexed: 6）を easyocr でテキスト抽出するスクリプト。

実行方法:
    cd C:\Users\Percy Iwai\Documents\defense_procurement_2nd
    python dev/ocr_page7_yosan_fy2025.py

出力: dev/ocr_page7_result.txt に保存し、コンソールにも表示。
"""
import fitz
import easyocr
from pathlib import Path

PDF_PATH = Path(__file__).parent.parent / "data" / "seisaku" / "yosan_fy2025.pdf"
OUT_PATH = Path(__file__).parent / "ocr_page7_result.txt"

doc = fitz.open(str(PDF_PATH))
print(f"総ページ数: {len(doc)}")

page = doc[6]  # 7ページ目（0-indexed: 6）
mat = fitz.Matrix(2, 2)  # 2x解像度
pix = page.get_pixmap(matrix=mat)
img_bytes = pix.tobytes("png")
print(f"画像サイズ: {pix.width}x{pix.height} px")
doc.close()

print("easyocr Reader を初期化中...")
reader = easyocr.Reader(["ja", "en"], gpu=False, verbose=False)

print("OCR実行中...")
results = reader.readtext(img_bytes, detail=1)
print(f"{len(results)} 個のテキスト領域を検出\n")

lines = []
for bbox, text, conf in results:
    line = f"{conf:.2f}  {text}"
    lines.append(line)

output = "\n".join(lines)

# ファイルに保存
OUT_PATH.write_text(output, encoding="utf-8")
print(f"結果を {OUT_PATH} に保存しました\n")
print("=" * 60)
print(output)
print("=" * 60)
