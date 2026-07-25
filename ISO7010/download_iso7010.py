#!/usr/bin/env python3
"""
Download ISO 7010 SVG files from Wikimedia Commons.

Usage:
    python download_iso7010.py

Requires:
    Python 3 and requests:
    pip install requests

The script searches Wikimedia Commons per ISO code, downloads the first
matching SVG file, and writes license/source metadata to download_log.csv.
Always verify the selected file and its individual license.
"""
from pathlib import Path
import csv, json, time
import requests

HERE = Path(__file__).resolve().parent
META = json.loads((HERE / "pictogrammen.json").read_text(encoding="utf-8"))
OUT = HERE / "afbeeldingen"
OUT.mkdir(exist_ok=True)

API = "https://commons.wikimedia.org/w/api.php"
HEADERS = {"User-Agent": "VIK-Bibliotheek-Goudsmidatelier/1.0 (educational use)"}
log = []

for item in META:
    code = item["code"]
    query = f'filetype:svg "ISO 7010" {code}'
    params = {
        "action": "query", "generator": "search", "gsrsearch": query,
        "gsrnamespace": 6, "gsrlimit": 10,
        "prop": "imageinfo", "iiprop": "url|extmetadata",
        "format": "json", "formatversion": 2
    }
    try:
        data = requests.get(API, params=params, headers=HEADERS, timeout=30).json()
        pages = data.get("query", {}).get("pages", [])
        # Prefer filenames containing the exact code.
        pages.sort(key=lambda p: (code.lower() not in p.get("title","").lower(), p.get("title","")))
        chosen = next((p for p in pages if p.get("imageinfo")), None)
        if not chosen:
            log.append([code, "NIET GEVONDEN", "", "", "", ""])
            continue
        info = chosen["imageinfo"][0]
        url = info["url"]
        ext = info.get("extmetadata", {})
        content = requests.get(url, headers=HEADERS, timeout=30).content
        filename = f"{code}.svg"
        (OUT / filename).write_bytes(content)
        log.append([
            code, "OK", chosen.get("title",""), url,
            ext.get("LicenseShortName", {}).get("value",""),
            ext.get("Artist", {}).get("value","")
        ])
        print(f"{code}: OK")
        time.sleep(0.15)
    except Exception as e:
        log.append([code, "FOUT", "", "", "", str(e)])
        print(f"{code}: FOUT - {e}")

with (HERE / "download_log.csv").open("w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["code","status","commons_titel","download_url","licentie","maker_of_bron"])
    w.writerows(log)

print(f"Klaar. Afbeeldingen: {OUT}")
