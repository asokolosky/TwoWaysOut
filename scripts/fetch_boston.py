"""Download Analyze Boston datasets into data/raw/ (gitignored).

Usage:
    python -m scripts.fetch_boston                 # everything
    python -m scripts.fetch_boston sam assessment  # just some

Raw files include owner names and contact addresses. They stay in data/raw/ and are never
committed; the preprocessing step drops those columns before anything reaches the app.
"""

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"

BASE = "https://data.boston.gov/dataset"
DATASETS = {
    # SAM addresses: address -> SAM ID, parcel, ward
    "sam": f"{BASE}/fc9562ca-02df-40bf-b4db-a36effb52ccc/resource/6d6cfc99-6f26-4974-bbb3-17b5dbad49a9/download/live_street_address_management_sam_addresses.csv",
    # Property assessment FY2026: land use, owner-occupancy, year built, heat type
    "assessment": f"{BASE}/e02c44d2-3c64-459c-8fe2-e1ce5f38a035/resource/ee73430d-96c0-423e-ad21-c4cfb54c8961/download/fy2026-property-assessment-data_rev.csv",
    # Used in Task 6
    "rentsmart": f"{BASE}/f506e000-b08c-4500-97c7-9f36e7ac125a/resource/dc615ff7-2ff3-416a-922b-f0f334f085d0/download/tmpcrprvfrb.csv",
    "violations": f"{BASE}/705244a6-70a6-4ff8-ab8e-56441aff18e7/resource/800a2663-1d6a-46e7-9356-bedb70f5332c/download/tmpilpychd0.csv",
    "permits": f"{BASE}/cd1ec3ff-6ebf-4a65-af68-8329eceab740/resource/6ddcd912-32a0-43df-9908-63574f8c7e77/download/tmpn5gbpnpu.csv",
}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _resolve(url: str) -> str:
    """Analyze Boston redirects to a signed S3 URL with an explicit ':443'. urllib sends that
    port in the Host header, which breaks the signature, so follow the redirect ourselves."""
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, method="HEAD", headers=HEADERS)
    try:
        opener.open(req, timeout=60)
        return url
    except urllib.error.HTTPError as exc:
        if exc.code in (301, 302, 303, 307, 308) and exc.headers.get("Location"):
            return exc.headers["Location"].replace(".com:443/", ".com/")
        raise


HEADERS = {"User-Agent": "TwoWaysOut/0.1 (hackathon)"}


def download(name: str, url: str) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    dest = RAW_DIR / f"{name}.csv"
    tmp = dest.with_suffix(".csv.part")
    req = urllib.request.Request(_resolve(url))
    start = time.monotonic()
    with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as out:
        total = 0
        while chunk := resp.read(1024 * 1024):
            out.write(chunk)
            total += len(chunk)
            print(f"\r  {name}: {total / 1e6:,.0f} MB", end="", flush=True)
    tmp.replace(dest)
    print(f"\r  {name}: {total / 1e6:,.1f} MB in {time.monotonic() - start:.0f}s -> {dest.name}")
    return dest


SNAPSHOT_DATES_FILE = "SNAPSHOT_DATES.json"


def _record_dates(fetched: list[str], today: str) -> None:
    """Per-dataset download dates. Preprocessing shows the oldest one as the snapshot date."""
    path = RAW_DIR / SNAPSHOT_DATES_FILE
    try:
        dates = json.loads(path.read_text()) if path.exists() else {}
    except json.JSONDecodeError:
        dates = {}
    dates.update({name: today for name in fetched})
    path.write_text(json.dumps(dates, indent=1, sort_keys=True))


def main(names: list[str]) -> None:
    names = names or list(DATASETS)
    unknown = set(names) - set(DATASETS)
    if unknown:
        sys.exit(f"Unknown dataset(s): {', '.join(sorted(unknown))}. Choose from {', '.join(DATASETS)}.")
    for name in names:
        download(name, DATASETS[name])
    today = time.strftime("%Y-%m-%d")
    _record_dates(names, today)
    # SNAPSHOT_DATE means "every dataset was downloaded on this date", so only a full fetch
    # updates it. A partial fetch leaves it alone (the per-dataset file covers that case).
    if set(names) == set(DATASETS):
        (RAW_DIR / "SNAPSHOT_DATE").write_text(today)


if __name__ == "__main__":
    main(sys.argv[1:])
