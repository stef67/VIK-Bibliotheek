#!/usr/bin/env python3
from __future__ import annotations

import csv
import html
import json
import random
import re
import time
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
HEADERS = {
    "User-Agent": (
        "VIK-Bibliotheek-Goudsmidatelier/1.0 "
        "(GitHub Actions; educational occupational-safety project)"
    )
}

OUT_DIR.mkdir(parents=True, exist_ok=True)

if not META_FILE.exists():
    raise FileNotFoundError(
        f"{META_FILE} ontbreekt. Plaats pictogrammen.json in de map ISO7010."
    )

items: list[dict[str, Any]] = json.loads(META_FILE.read_text(encoding="utf-8"))

retry = Retry(
    total=8,
    connect=8,
    read=8,
    status=8,
    backoff_factor=1.5,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=frozenset({"GET"}),
    respect_retry_after_header=True,
)

session = requests.Session()
session.headers.update(HEADERS)
session.mount("https://", HTTPAdapter(max_retries=retry))


def api_json(params: dict[str, Any], max_attempts: int = 6) -> dict[str, Any]:
    """Vraag JSON op en vang tijdelijke HTML-/rate-limit-antwoorden op."""
    last_error = ""
    for attempt in range(1, max_attempts + 1):
        response = session.get(API, params=params, timeout=90)
        content_type = response.headers.get("content-type", "")
        if response.status_code == 200 and "json" in content_type.lower():
            try:
                return response.json()
            except ValueError as exc:
                last_error = f"ongeldige JSON: {exc}"
        else:
            last_error = (
                f"status={response.status_code}, content-type={content_type}"
            )

        wait = min(90.0, 2**attempt) + random.random()
        print(f"Wikimedia-antwoord niet bruikbaar ({last_error}); wacht {wait:.1f}s")
        time.sleep(wait)

    raise RuntimeError(f"Geen geldig API-antwoord: {last_error}")


def search_candidates(code: str) -> list[dict[str, Any]]:
    """Zoek Wikimedia Commons-bestanden voor één ISO-code."""
    queries = [
        f'filetype:svg "ISO 7010" "{code}"',
        f'filetype:svg "ISO_7010_{code}"',
        f'filetype:svg "{code}" safety sign',
    ]

    results: dict[str, dict[str, Any]] = {}

    for query in queries:
        data = api_json(
            {
                "action": "query",
                "generator": "search",
                "gsrsearch": query,
                "gsrnamespace": 6,
                "gsrlimit": 20,
                "prop": "imageinfo",
                "iiprop": "url|extmetadata",
                "format": "json",
                "formatversion": 2,
            }
        )
        for page in data.get("query", {}).get("pages", []):
            if page.get("imageinfo"):
                results[page.get("title", "")] = page

        if results:
            break

        time.sleep(0.5)

    return list(results.values())


def score_candidate(page: dict[str, Any], code: str) -> int:
    """Geef voorrang aan SVG-bestanden met exact de juiste ISO-code."""
    title = page.get("title", "")
    low = title.lower()
    code_low = code.lower()
    score = 0

    if re.search(rf"(?<![a-z0-9]){re.escape(code_low)}(?![a-z0-9])", low):
        score += 100
    if f"iso_7010_{code_low}" in low or f"iso 7010 {code_low}" in low:
        score += 80
    if "iso 7010" in low or "iso_7010" in low or "iso7010" in low:
        score += 30
    if low.endswith(".svg"):
        score += 20

    return score


def clean_metadata(value: str) -> str:
    """Verwijder eenvoudige HTML uit Wikimedia metadata."""
    return re.sub(r"<[^>]+>", "", html.unescape(value or "")).strip()


log_rows: list[list[str]] = []

for index, item in enumerate(items, start=1):
    code = str(item["code"]).strip().upper()
    print(f"[{index}/{len(items)}] {code}")

    try:
        candidates = search_candidates(code)
        if not candidates:
            log_rows.append([code, "NIET GEVONDEN", "", "", "", "", ""])
            print("  Niet gevonden")
            time.sleep(0.8)
            continue

        candidates.sort(key=lambda page: score_candidate(page, code), reverse=True)
        chosen = candidates[0]
        chosen_score = score_candidate(chosen, code)

        # Vermijd het opslaan van een duidelijk onbetrouwbare zoekmatch.
        if chosen_score < 100:
            log_rows.append(
                [
                    code,
                    "HANDMATIGE CONTROLE",
                    chosen.get("title", ""),
                    "",
                    "",
                    "",
                    f"lage overeenkomstscore: {chosen_score}",
                ]
            )
            print(f"  Handmatige controle nodig (score {chosen_score})")
            time.sleep(0.8)
            continue

        info = chosen["imageinfo"][0]
        url = info["url"]
        metadata = info.get("extmetadata", {})

        response = session.get(url, timeout=90)
        response.raise_for_status()

        probe = response.content[:3000].lower()
        if b"<svg" not in probe:
            raise RuntimeError("het gedownloade bestand is geen SVG")

        (OUT_DIR / f"{code}.svg").write_bytes(response.content)

        license_name = clean_metadata(
            metadata.get("LicenseShortName", {}).get("value", "")
        )
        artist = clean_metadata(metadata.get("Artist", {}).get("value", ""))
        description_url = info.get("descriptionurl", "")

        log_rows.append(
            [
                code,
                "OK",
                chosen.get("title", ""),
                url,
                description_url,
                license_name,
                artist,
            ]
        )
        print(f"  OK: {chosen.get('title', '')}")

    except Exception as exc:  # continue with the next code
        log_rows.append([code, "FOUT", "", "", "", "", str(exc)])
        print(f"  FOUT: {exc}")

    time.sleep(0.8)

with LOG_FILE.open("w", newline="", encoding="utf-8-sig") as handle:
    writer = csv.writer(handle)
    writer.writerow(
        [
            "code",
            "status",
            "commons_titel",
            "download_url",
            "commons_beschrijvingspagina",
            "licentie",
            "maker_of_bron",
        ]
    )
    writer.writerows(log_rows)

ok_count = sum(row[1] == "OK" for row in log_rows)
manual_count = sum(row[1] == "HANDMATIGE CONTROLE" for row in log_rows)
missing_count = sum(row[1] == "NIET GEVONDEN" for row in log_rows)
error_count = sum(row[1] == "FOUT" for row in log_rows)

print(
    f"Klaar: {ok_count} gedownload, {manual_count} te controleren, "
    f"{missing_count} niet gevonden, {error_count} fouten."
)
