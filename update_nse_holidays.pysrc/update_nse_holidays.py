"""Refresh the NSE F&O trading holiday calendar from NSE's official endpoint.

The updater is deliberately conservative. It writes a year only when NSE returns
at least one valid trading date for that year. If NSE has not published a future
year yet, the report keeps the verified calendar and the normal strict calendar
check explains the missing coverage.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
HOLIDAYS = ROOT / "data" / "holidays.csv"
COVERAGE = ROOT / "data" / "holiday_coverage.json"
URL = "https://www.nseindia.com/api/holiday-master?type=trading"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NiftyReport/1.0)",
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://www.nseindia.com/",
}


def _date(value: object) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _rows(payload: object) -> list[tuple[dt.date, str]]:
    """Accept the current NSE response shape and ignore non-trading categories."""
    items = []
    if isinstance(payload, dict):
        # F&O is the calendar used by this project. Some NSE responses expose
        # only CM, so retain it as a documented fallback.
        items = payload.get("FO", []) or payload.get("CM", [])
    if not items and isinstance(payload, dict):
        for value in payload.values():
            if isinstance(value, list):
                items.extend(value)
    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        day = _date(item.get("tradingDate") or item.get("date") or item.get("holidayDate"))
        name = item.get("description") or item.get("holidayDescription") or item.get("name")
        if day and name:
            result.append((day, str(name).strip()))
    return sorted(set(result))


def main() -> None:
    response = requests.get(URL, headers=HEADERS, timeout=30)
    response.raise_for_status()
    rows = _rows(response.json())
    if not rows:
        raise RuntimeError("NSE returned no readable trading holidays")

    existing = []
    if HOLIDAYS.exists():
        with HOLIDAYS.open(newline="", encoding="utf-8") as handle:
            existing = [(dt.date.fromisoformat(row["date"]), row["name"])
                        for row in csv.DictReader(handle)]
    merged = sorted(set(existing + rows))
    with HOLIDAYS.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", "name"])
        writer.writerows((day.isoformat(), name) for day, name in merged)

    coverage = json.loads(COVERAGE.read_text(encoding="utf-8")) if COVERAGE.exists() else {}
    years = sorted({day.year for day, _ in merged})
    coverage["years"] = years
    sources = list(coverage.get("sources", []))
    source = "NSE official holiday-master API (trading calendar)"
    if source not in sources:
        sources.append(source)
    coverage["sources"] = sources
    COVERAGE.write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")
    print(f"NSE holiday calendar refreshed: {len(rows)} official rows, coverage through {max(years)}")


if __name__ == "__main__":
    main()
