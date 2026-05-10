"""Scrape ATLA jisseki index page to find all available PDFs."""
import requests
import re
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,*/*",
    "Accept-Language": "ja,en;q=0.9",
}

url = "https://www.mod.go.jp/atla/souhon/supply/jisseki/index.html"
r = requests.get(url, headers=HEADERS, timeout=30)
r.encoding = "utf-8"
soup = BeautifulSoup(r.text, "html.parser")

print(f"Status: {r.status_code}")
print(f"Title: {soup.title.string if soup.title else 'N/A'}")
print()

# Find all links
print("=== All links on page ===")
for a in soup.find_all("a", href=True):
    href = a["href"]
    text = a.get_text(strip=True)
    if href:
        print(f"  [{text}] -> {href}")

print()
print("=== Page text ===")
print(soup.get_text()[:3000])
