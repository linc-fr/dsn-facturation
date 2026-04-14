"""Organism reference registry and CTP labels for contribution reconciliation.

The canonical source of truth is ``data/organisms_reference.tsv``, loaded at
import time with strict fail-fast validation.
"""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Type-code → family mapping
# ---------------------------------------------------------------------------

TYPE_CODE_TO_FAMILY: dict[str, str] = {
    "URS": "urssaf",
    "MSA": "urssaf",
    "FIP": "pas",
    "AAR": "retraite",
    "CAM": "retraite",
    "CNI": "retraite",
    "AUD": "retraite",
    "CRC": "retraite",
    "CRN": "retraite",
    "FFS": "prevoyance",
    "CTI": "prevoyance",
    "FNM": "mutuelle",
    "OCI": "mutuelle",
    "PEM": "other",
    "CNB": "other",
}

# ---------------------------------------------------------------------------
# TSV loader with fail-fast validation
# ---------------------------------------------------------------------------

_DATA_DIR = Path(__file__).parent / "data"
_TSV_NAME = "organisms_reference.tsv"
_COMPLEMENTARY_FAMILY_OVERRIDES_TSV = "complementary_family_overrides.tsv"


def _load_registry(tsv_path: Path) -> dict[str, tuple[str, str, str]]:
    """Load and validate the organism registry from the canonical TSV.

    Returns dict mapping organism_id → (label, type_code, family).
    Raises RuntimeError on any validation failure.
    """
    # 1. File exists
    if not tsv_path.is_file():
        raise RuntimeError(f"{_TSV_NAME} not found at {tsv_path}")

    lines = tsv_path.read_text(encoding="utf-8").splitlines()

    # 2. Non-empty
    if not lines:
        raise RuntimeError(f"{_TSV_NAME} is empty")

    registry: dict[str, tuple[str, str, str]] = {}
    seen_ids: dict[str, int] = {}  # organism_id → first line number

    for line_num, raw_line in enumerate(lines, start=1):
        if not raw_line.strip():
            continue  # skip blank lines

        cols = raw_line.split("\t")

        # 3. Header row check
        if cols[0].strip().lower() == "organism_id":
            raise RuntimeError(
                f"{_TSV_NAME} line {line_num}: contains header row — remove it"
            )

        # 4. Column count
        if len(cols) != 4:
            raise RuntimeError(
                f"{_TSV_NAME} line {line_num}: expected 4 columns, got {len(cols)}"
            )

        organism_id = cols[0].strip()
        label = cols[1].strip()
        type_code = cols[2].strip()

        # 5. Required fields
        if not organism_id or not type_code:
            raise RuntimeError(
                f"{_TSV_NAME} line {line_num}: missing organism_id or type_code"
            )

        # 6. Known type_code
        if type_code not in TYPE_CODE_TO_FAMILY:
            raise RuntimeError(
                f"{_TSV_NAME} line {line_num}: unknown type_code '{type_code}'"
            )

        # 7. No duplicate keys
        if organism_id in seen_ids:
            raise RuntimeError(
                f"{_TSV_NAME}: duplicate organism_id '{organism_id}' "
                f"at lines {seen_ids[organism_id]} and {line_num}"
            )

        seen_ids[organism_id] = line_num
        family = TYPE_CODE_TO_FAMILY[type_code]
        registry[organism_id] = (label, type_code, family)

    # Final non-empty check (all lines were blank)
    if not registry:
        raise RuntimeError(f"{_TSV_NAME} is empty")

    return registry


ORGANISM_REGISTRY: dict[str, tuple[str, str, str]] = _load_registry(
    _DATA_DIR / _TSV_NAME
)


def _load_complementary_family_overrides(
    tsv_path: Path,
) -> dict[tuple[str, str], str]:
    """Load explicit complementary family overrides keyed by organism+contract."""
    if not tsv_path.is_file():
        raise RuntimeError(f"{_COMPLEMENTARY_FAMILY_OVERRIDES_TSV} not found at {tsv_path}")

    lines = tsv_path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise RuntimeError(f"{_COMPLEMENTARY_FAMILY_OVERRIDES_TSV} is empty")

    overrides: dict[tuple[str, str], str] = {}
    for line_num, raw_line in enumerate(lines, start=1):
        if not raw_line.strip():
            continue
        cols = raw_line.split("\t")
        if cols[0].strip().lower() == "organism_id":
            raise RuntimeError(
                f"{_COMPLEMENTARY_FAMILY_OVERRIDES_TSV} line {line_num}: contains header row — remove it"
            )
        if len(cols) != 3:
            raise RuntimeError(
                f"{_COMPLEMENTARY_FAMILY_OVERRIDES_TSV} line {line_num}: expected 3 columns, got {len(cols)}"
            )
        organism_id = cols[0].strip()
        contract_ref = cols[1].strip()
        family = cols[2].strip()
        if not organism_id or not contract_ref or not family:
            raise RuntimeError(
                f"{_COMPLEMENTARY_FAMILY_OVERRIDES_TSV} line {line_num}: missing organism_id, contract_ref or family"
            )
        if family not in {"prevoyance", "mutuelle"}:
            raise RuntimeError(
                f"{_COMPLEMENTARY_FAMILY_OVERRIDES_TSV} line {line_num}: unsupported family '{family}'"
            )
        key = (organism_id, contract_ref)
        if key in overrides:
            raise RuntimeError(
                f"{_COMPLEMENTARY_FAMILY_OVERRIDES_TSV}: duplicate key {key!r} at line {line_num}"
            )
        overrides[key] = family

    if not overrides:
        raise RuntimeError(f"{_COMPLEMENTARY_FAMILY_OVERRIDES_TSV} is empty")

    return overrides


COMPLEMENTARY_FAMILY_OVERRIDES: dict[tuple[str, str], str] = _load_complementary_family_overrides(
    _DATA_DIR / _COMPLEMENTARY_FAMILY_OVERRIDES_TSV
)

# ---------------------------------------------------------------------------
# CTP labels (from publicodes 13.3 — S21.G00.23 cotisation agrégée)
# ---------------------------------------------------------------------------

CTP_LABELS: dict[str, str] = {
    "001": "Rémunération brute non plafonnée",
    "002": "Salaire brut chômage",
    "003": "Réduction salariale heures sup",
    "004": "Déduction patronale heures sup ≤20 salariés",
    "010": "Salaire de base",
    "017": "Heures supplémentaires exceptionnelles",
    "018": "Heures supplémentaires structurelles",
    "019": "Activité partielle",
    "027": "Contribution au dialogue social",
    "060": "CSG CRDS activité partielle",
    "100": "RG cas général",
    "206": "Salariés non résidents actifs",
    "236": "FNAL taux plein",
    "260": "CSG CRDS régime général",
    "332": "FNAL plafonné",
    "381": "Maladie Alsace Moselle",
    "423": "Contrib assurance chômage apprentis",
    "430": "Complément cotisation AF",
    "479": "Forfait social 8",
    "635": "Complément cotisation maladie",
    "668": "Réduction générale étendue",
    "669": "Régul réduction générale étendue",
    "719": "Contribution ARTL13712 CSS",
    "726": "Apprentis sect privé inf seuil",
    "734": "JEI exonération taux plein",
    "772": "Contributions assurance chômage",
    "863": "RG mandataires sociaux",
    "900": "Versement mobilité",
    "937": "Cotisations AGS cas général",
    "959": "CFP entreprise < 11 salariés",
    "992": "TA principale hors Alsace Moselle",
}

# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


def lookup_organism(organism_id: str) -> tuple[str | None, str | None, str | None]:
    """Return (label, type_code, family) or (None, None, None) if unknown."""
    return ORGANISM_REGISTRY.get(organism_id, (None, None, None))


def lookup_ctp(ctp_code: str) -> str | None:
    """Return CTP label or None if unknown."""
    return CTP_LABELS.get(ctp_code)


def lookup_complementary_family_override(
    organism_id: str,
    contract_ref: str,
) -> str | None:
    """Return explicit family override for one complementary contract."""
    return COMPLEMENTARY_FAMILY_OVERRIDES.get((organism_id, contract_ref))
