"""Sequential block reconstruction for DSN contribution reconciliation.

Reconstructs parent-child block groups from flat record lists, following the
same sequential-position logic as the parser's S54 handling.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from dsn_extractor.parser import DSNRecord, EmployeeBlock, EstablishmentBlock


# ---------------------------------------------------------------------------
# Record lookup helper (same pattern as extractors.py)
# ---------------------------------------------------------------------------


def _find_value(records: list[DSNRecord], code: str) -> str | None:
    for r in records:
        if r.code == code:
            return r.raw_value
    return None


# ---------------------------------------------------------------------------
# Block group dataclass
# ---------------------------------------------------------------------------


@dataclass
class BlockGroup:
    """A contiguous block of DSN records sharing a prefix, with children."""

    prefix: str
    records: list[DSNRecord] = field(default_factory=list)
    children: list[BlockGroup] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Establishment-level block groups
# ---------------------------------------------------------------------------


@dataclass
class EstablishmentBlockGroups:
    """Reconstructed block groups for one establishment."""

    s15_blocks: list[BlockGroup] = field(default_factory=list)
    s20_blocks: list[BlockGroup] = field(default_factory=list)  # children = S55
    s22_blocks: list[BlockGroup] = field(default_factory=list)  # children = S23
    warnings: list[str] = field(default_factory=list)


def group_establishment_blocks(
    est_block: EstablishmentBlock,
) -> EstablishmentBlockGroups:
    """Reconstruct S15, S20/S55, S22/S23 block groups from establishment records.

    Iterates sequentially over est_block.records maintaining parent pointers.
    S55 attaches to current S20; S23 attaches to current S22.
    Orphan children emit warnings and are stored but excluded from reconciliation.
    """
    result = EstablishmentBlockGroups()

    current_s15: BlockGroup | None = None
    current_s20: BlockGroup | None = None
    current_s22: BlockGroup | None = None
    current_s55: BlockGroup | None = None
    current_s23: BlockGroup | None = None

    def _flush_s15() -> None:
        nonlocal current_s15
        if current_s15 is not None:
            result.s15_blocks.append(current_s15)
            current_s15 = None

    def _flush_s55() -> None:
        nonlocal current_s55
        if current_s55 is not None:
            if current_s20 is not None:
                current_s20.children.append(current_s55)
            else:
                result.warnings.append(
                    f"orphan_s55_block at line {current_s55.records[0].line_number}"
                )
            current_s55 = None

    def _flush_s23() -> None:
        nonlocal current_s23
        if current_s23 is not None:
            if current_s22 is not None:
                current_s22.children.append(current_s23)
            else:
                result.warnings.append(
                    f"orphan_s23_block at line {current_s23.records[0].line_number}"
                )
            current_s23 = None

    def _flush_s20() -> None:
        nonlocal current_s20
        _flush_s55()
        if current_s20 is not None:
            result.s20_blocks.append(current_s20)
            current_s20 = None

    def _flush_s22() -> None:
        nonlocal current_s22
        _flush_s23()
        if current_s22 is not None:
            result.s22_blocks.append(current_s22)
            current_s22 = None

    for record in est_block.records:
        code = record.code

        # S21.G00.15 — adhesion prévoyance/mutuelle
        if code.startswith("S21.G00.15."):
            if code == "S21.G00.15.001":
                _flush_s15()
                current_s15 = BlockGroup(prefix="S21.G00.15", records=[record])
            elif current_s15 is not None:
                current_s15.records.append(record)
            continue

        # S21.G00.20 — versement organisme
        if code.startswith("S21.G00.20."):
            if code == "S21.G00.20.001":
                _flush_s20()
                _flush_s22()
                current_s20 = BlockGroup(prefix="S21.G00.20", records=[record])
            elif current_s20 is not None:
                current_s20.records.append(record)
            continue

        # S21.G00.55 — composant de versement (child of S20)
        if code.startswith("S21.G00.55."):
            if code == "S21.G00.55.001":
                _flush_s55()
                current_s55 = BlockGroup(prefix="S21.G00.55", records=[record])
            elif current_s55 is not None:
                current_s55.records.append(record)
            continue

        # S21.G00.22 — bordereau de cotisation due
        if code.startswith("S21.G00.22."):
            if code == "S21.G00.22.001":
                _flush_s22()
                current_s22 = BlockGroup(prefix="S21.G00.22", records=[record])
            elif current_s22 is not None:
                current_s22.records.append(record)
            continue

        # S21.G00.23 — cotisation agrégée (child of S22)
        if code.startswith("S21.G00.23."):
            if code == "S21.G00.23.001":
                _flush_s23()
                current_s23 = BlockGroup(prefix="S21.G00.23", records=[record])
            elif current_s23 is not None:
                current_s23.records.append(record)
            continue

    # EOF flush
    _flush_s15()
    _flush_s20()
    _flush_s22()

    return result


# ---------------------------------------------------------------------------
# Employee-level block groups
# ---------------------------------------------------------------------------


@dataclass
class EmployeeBlockGroups:
    """Reconstructed block groups for one employee."""

    s50_blocks: list[BlockGroup] = field(default_factory=list)
    s70_blocks: list[BlockGroup] = field(default_factory=list)
    s78_blocks: list[BlockGroup] = field(default_factory=list)  # children = S81
    warnings: list[str] = field(default_factory=list)


def group_employee_blocks(emp_block: EmployeeBlock) -> EmployeeBlockGroups:
    """Reconstruct S50, S70, S78/S81 block groups from employee records.

    S79 records are ignored (they appear between S78 and S81 but are not used
    for reconciliation and must not break the 78→81 parent-child linkage).

    S70 has no ``.001`` starter in the normative layout. Real files emit its
    fields in ascending suffix order, so a new S70 block starts on the first
    S70 record after a non-S70 record, and also whenever the suffix order
    restarts (for example ``...70.013`` followed by ``...70.004``).
    """
    result = EmployeeBlockGroups()

    current_s50: BlockGroup | None = None
    current_s70: BlockGroup | None = None
    current_s78: BlockGroup | None = None
    current_s81: BlockGroup | None = None
    previous_s70_suffix: int | None = None

    def _flush_s50() -> None:
        nonlocal current_s50
        if current_s50 is not None:
            result.s50_blocks.append(current_s50)
            current_s50 = None

    def _flush_s70() -> None:
        nonlocal current_s70, previous_s70_suffix
        if current_s70 is not None:
            result.s70_blocks.append(current_s70)
            current_s70 = None
        previous_s70_suffix = None

    def _flush_s81() -> None:
        nonlocal current_s81
        if current_s81 is not None:
            if current_s78 is not None:
                current_s78.children.append(current_s81)
            else:
                result.warnings.append(
                    f"orphan_s81_block at line {current_s81.records[0].line_number}"
                )
            current_s81 = None

    def _flush_s78() -> None:
        nonlocal current_s78
        _flush_s81()
        if current_s78 is not None:
            result.s78_blocks.append(current_s78)
            current_s78 = None

    for record in emp_block.records:
        code = record.code

        # S21.G00.50 — rémunération
        if code.startswith("S21.G00.50."):
            if code == "S21.G00.50.001":
                _flush_s50()
                current_s50 = BlockGroup(prefix="S21.G00.50", records=[record])
            elif current_s50 is not None:
                current_s50.records.append(record)
            continue

        # S21.G00.70 — affiliation prévoyance/mutuelle
        if code.startswith("S21.G00.70."):
            suffix = int(code.rsplit(".", 1)[1])
            if current_s70 is None or (
                previous_s70_suffix is not None and suffix <= previous_s70_suffix
            ):
                _flush_s70()
                current_s70 = BlockGroup(prefix="S21.G00.70", records=[record])
            elif current_s70 is not None:
                current_s70.records.append(record)
            previous_s70_suffix = suffix
            continue

        # S21.G00.78 — base assujettie
        if code.startswith("S21.G00.78."):
            if code == "S21.G00.78.001":
                _flush_s78()
                current_s78 = BlockGroup(prefix="S21.G00.78", records=[record])
            elif current_s78 is not None:
                current_s78.records.append(record)
            continue

        # S21.G00.79 — composant de base assujettie (ignored, don't break 78→81)
        if code.startswith("S21.G00.79."):
            continue

        # S21.G00.81 — cotisation individuelle (child of S78)
        if code.startswith("S21.G00.81."):
            if code == "S21.G00.81.001":
                _flush_s81()
                current_s81 = BlockGroup(prefix="S21.G00.81", records=[record])
            elif current_s81 is not None:
                current_s81.records.append(record)
            continue

    # EOF flush
    _flush_s50()
    _flush_s70()
    _flush_s78()

    return result
