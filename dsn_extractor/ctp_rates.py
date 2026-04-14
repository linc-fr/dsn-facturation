"""Reference rates for URSSAF CTP controls.

The canonical source is a checked-in TSV artifact curated from the full
authoritative CTP rate table provided by the user.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from decimal import Decimal

from dsn_extractor.normalize import normalize_decimal


@dataclass(frozen=True)
class CTPRateReference:
    ctp_code: str
    label: str
    short_label: str | None
    fmt: str | None
    rate_plafonne: Decimal | None
    rate_deplafonne: Decimal | None
    rate_at: Decimal | None
    effective_date: dt.date


_DATA_DIR = Path(__file__).parent / "data"
_TSV_NAME = "ctp_rate_reference.tsv"


def _parse_date(raw: str, line_num: int) -> dt.date:
    try:
        day, month, year = raw.split("/")
        return dt.date(int(year), int(month), int(day))
    except Exception as exc:  # pragma: no cover - fail-fast path
        raise RuntimeError(
            f"{_TSV_NAME} line {line_num}: invalid effective_date {raw!r}"
        ) from exc


def _parse_decimal(raw: str) -> Decimal | None:
    raw = raw.strip()
    if not raw:
        return None
    return normalize_decimal(raw)


def _load_ctp_rate_reference(tsv_path: Path) -> dict[str, list[CTPRateReference]]:
    if not tsv_path.is_file():
        raise RuntimeError(f"{_TSV_NAME} not found at {tsv_path}")

    lines = tsv_path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise RuntimeError(f"{_TSV_NAME} is empty")

    refs: dict[str, list[CTPRateReference]] = {}
    for line_num, raw_line in enumerate(lines, start=1):
        if not raw_line.strip():
            continue
        cols = raw_line.split("\t")
        if len(cols) != 8:
            raise RuntimeError(
                f"{_TSV_NAME} line {line_num}: expected 8 columns, got {len(cols)}"
            )

        ctp_code = cols[0].strip()
        label = cols[1].strip()
        short_label = cols[2].strip() or None
        fmt = cols[3].strip() or None
        if not ctp_code or not label:
            raise RuntimeError(
                f"{_TSV_NAME} line {line_num}: missing ctp_code or label"
            )
        if ctp_code.lower().startswith(("ctp", "code")):
            raise RuntimeError(
                f"{_TSV_NAME} line {line_num}: contains header row — remove it"
            )

        ref = CTPRateReference(
            ctp_code=ctp_code,
            label=label,
            short_label=short_label,
            fmt=fmt,
            rate_plafonne=_parse_decimal(cols[4]),
            rate_deplafonne=_parse_decimal(cols[5]),
            rate_at=_parse_decimal(cols[6]),
            effective_date=_parse_date(cols[7].strip(), line_num),
        )
        refs.setdefault(ctp_code, []).append(ref)

    if not refs:
        raise RuntimeError(f"{_TSV_NAME} is empty")

    for ctp_code in refs:
        refs[ctp_code].sort(key=lambda ref: ref.effective_date)

    # Reject duplicate effective_date per code (exact dup or conflicting rates)
    for ctp_code, entries in refs.items():
        for i in range(1, len(entries)):
            if entries[i].effective_date == entries[i - 1].effective_date:
                raise RuntimeError(
                    f"{_TSV_NAME}: duplicate effective_date "
                    f"{entries[i].effective_date.strftime('%d/%m/%Y')} "
                    f"for ctp_code '{ctp_code}'"
                )

    return refs


def _validate_reference_coverage(refs: dict[str, list[CTPRateReference]]) -> None:
    """Acceptance checks: dataset completeness after ingestion."""
    total_rows = sum(len(v) for v in refs.values())
    if total_rows < 500:
        raise RuntimeError(
            f"{_TSV_NAME}: expected ≥500 rows (full table), got {total_rows}. "
            "Restore from the authoritative CTP table."
        )
    ctp_100 = refs.get("100", [])
    ctp_100_dates = {r.effective_date for r in ctp_100}
    for expected in [dt.date(2024, 1, 1), dt.date(2026, 1, 1)]:
        if expected not in ctp_100_dates:
            raise RuntimeError(
                f"{_TSV_NAME}: CTP 100 missing expected effective_date {expected}"
            )
    required_codes = {"100", "260", "332", "430", "635", "668", "726", "772", "937"}
    missing = required_codes - set(refs.keys())
    if missing:
        raise RuntimeError(
            f"{_TSV_NAME}: missing required CTP codes: {sorted(missing)}"
        )


CTP_RATE_REFERENCE = _load_ctp_rate_reference(_DATA_DIR / _TSV_NAME)
_validate_reference_coverage(CTP_RATE_REFERENCE)


def lookup_ctp_reference(
    ctp_code: str,
    reference_date: dt.date | None,
) -> CTPRateReference | None:
    rows = CTP_RATE_REFERENCE.get(ctp_code)
    if not rows:
        return None

    if reference_date is None:
        return None

    selected: CTPRateReference | None = None
    for row in rows:
        if row.effective_date <= reference_date:
            selected = row
        else:
            break
    return selected
