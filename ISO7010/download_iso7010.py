#!/usr/bin/env python3
from __future__ import annotations
import csv, json, re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

HERE = Path(__file__).resolve().parent
META_FILE = HERE / "pictogrammen.json"
OUT_DIR = HERE / "afbeeldingen"
LOG_FILE = HERE / "download_log.csv"
API = "https://commons.wikimedia.org/w/api.php"
HEADERS = {"User-Agent": "VIK-Bibliotheek-Goudsmidatelier/1.1"}

OUT_DIR.mkdir(parents=True, exist_ok=True)
items = json.loads(META_FILE.read_text(encoding="utf-8"))

def session():
    retry = Retry(total=5, connect=5, read=5, status=5, backoff_factor=0.7,
                  status_forcelist=[429,500,502,503,504],
                  allowed_methods=frozenset({"GET"}), respect_retry_after_header=True)
    s = requests.Session()
    s.headers.update(HEADERS)
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s

def search(code):
    s = session()
    for q in [f'filetype:svg "ISO 7010" "{code}"', f'filetype:svg "ISO_7010_{code}"']:
        r = s.get(API, params={"action":"query","generator":"search","gsrsearch":q,
            "gsrnamespace":6,"gsrlimit":10,"prop":"imageinfo",
            "iiprop":"url|extmetadata","format":"json","formatversion":2}, timeout=45)
        r.raise_for_status()
        pages=[p for p in r.json().get("query",{}).get("pages",[]) if p.get("imageinfo")]
        if pages: return pages
    return []

def score(page, code):
    title=page.get("title","").lower(); c=code.lower(); val=0
    if re.search(rf"(?<![a-z0-9]){re.escape(c)}(?![a-z0-9])", title): val += 100
    if f"iso_7010_{c}" in title: val += 80
    if "iso 7010" in title or "iso_7010" in title or "iso7010" in title: val += 30
    if title.endswith(".svg"): val += 20
    return val

def process(item):
    code=str(item["code"]).strip().upper()
    target=OUT_DIR/f"{code}.svg"
    if target.exists() and target.stat().st_size > 100:
        return [code,"BESTAAT","","","","",""]
    pages=search(code)
    if not pages: return [code,"NIET GEVONDEN","","","","",""]
    pages.sort(key=lambda p: score(p,code), reverse=True)
    chosen=pages[0]
    if score(chosen,code) < 100:
        return [code,"HANDMATIGE CONTROLE",chosen.get("title",""),"","","",""]
    info=chosen["imageinfo"][0]
    r=session().get(info["url"], timeout=45); r.raise_for_status()
    if b"<svg" not in r.content[:3000].lower():
        return [code,"FOUT",chosen.get("title",""),info["url"],"","","geen SVG"]
    target.write_bytes(r.content)
    meta=info.get("extmetadata",{})
    return [code,"OK",chosen.get("title",""),info["url"],info.get("descriptionurl",""),
            meta.get("LicenseShortName",{}).get("value",""),
            meta.get("Artist",{}).get("value","")]

rows=[]
with ThreadPoolExecutor(max_workers=6) as ex:
    futures={ex.submit(process,item):item for item in items}
    for f in as_completed(futures):
        code=str(futures[f]["code"]).strip().upper()
        try: row=f.result()
        except Exception as e: row=[code,"FOUT","","","","",str(e)]
        rows.append(row); print(f"{row[0]}: {row[1]}")

rows.sort(key=lambda r:r[0])
with LOG_FILE.open("w",newline="",encoding="utf-8-sig") as h:
    w=csv.writer(h)
    w.writerow(["code","status","commons_titel","download_url","commons_beschrijvingspagina","licentie","maker_of_bron"])
    w.writerows(rows)
print("Klaar.")
