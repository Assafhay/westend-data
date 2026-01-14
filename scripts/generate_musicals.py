import csv
import json
import os
import sys
from datetime import date, datetime
from urllib.request import urlopen

OPEN_ENDED_PLACEHOLDERS = {"", "none", "2099-12-31", None}

KEEP_EMPTY_AS_EMPTY_STRING = True
SOON_WINDOW_DAYS_DEFAULT = 60  # can override via env var SOON_WINDOW_DAYS

def parse_date(s: str):
    s = (s or "").strip()
    if not s or s.lower() == "none":
        return None
    return datetime.strptime(s, "%Y-%m-%d").date()

def canonical_key(k: str) -> str:
    k = (k or "").strip()
    if k == "ID":
        return "id"
    return k

def normalize_cell(v: str):
    if v is None:
        return "" if KEEP_EMPTY_AS_EMPTY_STRING else None

    s = v.strip()
    if s == "":
        return "" if KEEP_EMPTY_AS_EMPTY_STRING else None

    if s.lower() == "none":
        return "none"

    if s.isdigit() or (s.startswith("-") and s[1:].isdigit()):
        try:
            return int(s)
        except Exception:
            pass

    if "." in s and any(ch.isdigit() for ch in s):
        try:
            return float(s)
        except Exception:
            pass

    return s

def compute_status(start, close, today):
    if start and today < start:
        return "future"
    if close and today > close:
        return "inactive"
    return "active"

def is_visible_on_app(obj) -> bool:
    v = obj.get("visible_on_app", 0)  # missing defaults hidden (safer)
    if isinstance(v, str):
        v = v.strip()
    return (v == 1) or (v == "1")

def compute_soon_flags(status: str, start, close, today, window_days: int):
    days_until_start = None
    if start:
        days_until_start = (start - today).days

    days_until_close = None
    if close:
        days_until_close = (close - today).days

    coming_soon = (
        status == "future"
        and days_until_start is not None
        and 0 <= days_until_start <= window_days
    )

    closing_soon = (
        status == "active"
        and days_until_close is not None
        and 0 <= days_until_close <= window_days
    )

    return coming_soon, closing_soon, days_until_start, days_until_close

def main():
    sheet_csv_url = os.environ.get("SHEET_CSV_URL")
    out_path = os.environ.get("OUT_PATH", "musicals.json")
    window_days = int(os.environ.get("SOON_WINDOW_DAYS", SOON_WINDOW_DAYS_DEFAULT))

    if not sheet_csv_url:
        print("Missing SHEET_CSV_URL env var", file=sys.stderr)
        sys.exit(1)

    today = date.today()

    csv_bytes = urlopen(sheet_csv_url).read()
    csv_text = csv_bytes.decode("utf-8", errors="replace").splitlines()
    reader = csv.DictReader(csv_text)

    musicals = []
    seen_ids = set()

    for row in reader:
        if not any((v or "").strip() for v in row.values()):
            continue

        obj = {}
        for raw_k, raw_v in row.items():
            key = canonical_key(raw_k)
            if not key:
                continue
            obj[key] = normalize_cell(raw_v)

        # Enforce visibility at generation time
        if not is_visible_on_app(obj):
            continue

        show_id = obj.get("id")
        if isinstance(show_id, str):
            show_id = show_id.strip()

        if not show_id:
            print("Row missing ID; skipping row.", file=sys.stderr)
            continue

        if show_id in seen_ids:
            print(f"Duplicate id '{show_id}' detected; skipping duplicate row.", file=sys.stderr)
            continue
        seen_ids.add(show_id)

        # Dates
        start = parse_date(str(obj.get("start_date") or ""))
        close_raw = str(obj.get("close_date") or "").strip()

        close = None
        if close_raw and close_raw not in OPEN_ENDED_PLACEHOLDERS and close_raw.lower() != "none":
            close = parse_date(close_raw)

        # Keep date strings in output (same style as before)
        obj["start_date"] = start.isoformat() if start else (obj.get("start_date") or "")
        obj["close_date"] = close_raw if close_raw else (obj.get("close_date") or "")

        # Status
        status = compute_status(start, close, today)
        obj["status"] = status

        # Soon flags
        coming_soon, closing_soon, days_until_start, days_until_close = compute_soon_flags(
            status=status,
            start=start,
            close=close,
            today=today,
            window_days=window_days,
        )
        obj["coming_soon"] = coming_soon
        obj["closing_soon"] = closing_soon
        obj["days_until_start"] = days_until_start
        obj["days_until_close"] = days_until_close

        musicals.append(obj)

    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(musicals, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")

    print(f"Wrote {len(musicals)} musicals to {out_path}")

if __name__ == "__main__":
    main()
