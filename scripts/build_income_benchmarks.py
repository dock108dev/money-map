#!/usr/bin/env python3
"""Build the checked-in, public-only state AGI benchmark artifact."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from urllib.request import urlopen

IRS_CSV_URL = "https://www.irs.gov/pub/irs-soi/22instateshares.csv"
BLS_API_URL = (
    "https://api.bls.gov/publicAPI/v2/timeseries/data/CUUR0000SA0?startyear=2022&endyear=2026"
)
IRS_LANDING_URL = (
    "https://www.irs.gov/statistics/"
    "soi-tax-stats-adjusted-gross-income-agi-percentile-data-by-state"
)
BLS_SERIES_URL = "https://data.bls.gov/timeseries/CUUR0000SA0"
OUTPUT = (
    Path(__file__).resolve().parents[1] / "src" / "paycheck_map" / "data" / "income_benchmarks.json"
)
PERCENTILES = {
    "top_50": "agi_50",
    "top_25": "agi_25",
    "top_10": "agi_10",
    "top_5": "agi_05",
    "top_1": "agi_01",
}


def _download(url: str) -> bytes:
    with urlopen(url, timeout=30) as response:
        return response.read()


def _cpi_values(payload: bytes) -> tuple[Decimal, str, Decimal, str]:
    parsed = json.loads(payload)
    rows = parsed["Results"]["series"][0]["data"]
    base = [
        Decimal(row["value"])
        for row in rows
        if row["year"] == "2022" and row["period"].startswith("M")
    ]
    if len(base) != 12:
        raise RuntimeError("BLS response did not contain all twelve 2022 CPI-U observations")
    latest = next(
        (row for row in rows if row.get("latest") == "true" and row["value"] not in {"", "-"}),
        None,
    )
    if latest is None:
        raise RuntimeError("BLS response did not identify a latest CPI-U observation")
    return (
        sum(base, Decimal("0")) / Decimal("12"),
        "2022 annual average",
        Decimal(latest["value"]),
        f"{latest['periodName']} {latest['year']}",
    )


def main() -> None:
    irs_payload = _download(IRS_CSV_URL)
    bls_payload = _download(BLS_API_URL)
    base_cpi, base_label, current_cpi, current_label = _cpi_values(bls_payload)
    factor = current_cpi / base_cpi
    states: dict[str, object] = {}
    for row in csv.DictReader(io.StringIO(irs_payload.decode("utf-8-sig"))):
        state = row["state"]
        if state == "US":
            continue
        thresholds: dict[str, dict[str, str]] = {}
        for label, column in PERCENTILES.items():
            source = Decimal(row[column])
            normalized = (source * factor).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            thresholds[label] = {
                "source_amount": str(source.quantize(Decimal("0.01"))),
                "normalized_amount": str(normalized),
            }
        states[state] = {
            "name": row["state_name"],
            "thresholds": thresholds,
        }

    artifact = {
        "version": "irs-state-agi-2022-cpi-u-2026-06-v1",
        "definition": (
            "AGI floors for selected descending cumulative percentiles of positive-AGI "
            "individual income tax returns; these are not household spending budgets."
        ),
        "source_year": 2022,
        "normalized_dollar_basis": current_label,
        "retrieved_at": datetime.now(UTC).isoformat(),
        "sources": {
            "irs": IRS_LANDING_URL,
            "irs_csv": IRS_CSV_URL,
            "irs_sha256": hashlib.sha256(irs_payload).hexdigest(),
            "bls_cpi_u": BLS_SERIES_URL,
            "bls_api": BLS_API_URL,
            "bls_sha256": hashlib.sha256(bls_payload).hexdigest(),
            "base_cpi": str(base_cpi.quantize(Decimal("0.001"))),
            "base_cpi_period": base_label,
            "current_cpi": str(current_cpi),
            "current_cpi_period": current_label,
            "normalization_factor": str(factor.quantize(Decimal("0.000001"))),
        },
        "states": states,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {len(states)} state and district benchmarks to {OUTPUT}")


if __name__ == "__main__":
    main()
