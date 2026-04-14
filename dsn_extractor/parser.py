"""Line parsing and block segmentation for DSN files."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import NamedTuple

LINE_RE = re.compile(r"^(S\d+\.G\d+\.\d+\.\d+),'(.*)'$")

FILE_LEVEL_PREFIXES = ("S10.", "S20.", "S90.")
ESTABLISHMENT_DECL_CODE = "S21.G00.06.001"
ESTABLISHMENT_IDENTITY_CODE = "S21.G00.11.001"
EMPLOYEE_START_CODE = "S21.G00.30.001"
S54_PREFIX = "S21.G00.54."


class DSNRecord(NamedTuple):
    """A single parsed DSN line."""

    code: str
    raw_value: str
    line_number: int


@dataclass
class EmployeeBlock:
    """All records belonging to one employee."""

    records: list[DSNRecord] = field(default_factory=list)
    establishment_index: int | None = None


@dataclass
class EstablishmentBlock:
    """Records for one establishment plus its employees and S54 groups."""

    records: list[DSNRecord] = field(default_factory=list)
    employee_blocks: list[EmployeeBlock] = field(default_factory=list)
    s54_blocks: list[list[DSNRecord]] = field(default_factory=list)


@dataclass
class ParsedDSN:
    """Complete parse result for one DSN file."""

    all_records: list[DSNRecord]
    file_level_records: list[DSNRecord]
    establishments: list[EstablishmentBlock]
    unassigned_employee_blocks: list[EmployeeBlock]
    unassigned_s54_blocks: list[list[DSNRecord]]
    warnings: list[str]
    skipped_lines: list[tuple[int, str]]


def parse_lines(text: str) -> tuple[list[DSNRecord], list[tuple[int, str]]]:
    """Parse raw DSN text into ordered records.

    Returns (records, skipped_lines). Blank lines are silently ignored.
    Non-blank lines that don't match the DSN regex are captured in skipped_lines.
    """
    # Strip BOM from start of text
    if text.startswith("\ufeff"):
        text = text[1:]

    records: list[DSNRecord] = []
    skipped: list[tuple[int, str]] = []

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped:
            continue
        m = LINE_RE.match(stripped)
        if m:
            records.append(DSNRecord(code=m.group(1), raw_value=m.group(2), line_number=line_number))
        else:
            skipped.append((line_number, stripped))

    return records, skipped


def segment(records: list[DSNRecord], skipped_lines: list[tuple[int, str]]) -> ParsedDSN:
    """Segment ordered records into file/establishment/employee/S54 layers."""
    file_level: list[DSNRecord] = []
    establishments: list[EstablishmentBlock] = []
    unassigned_employees: list[EmployeeBlock] = []
    unassigned_s54: list[list[DSNRecord]] = []
    warnings: list[str] = []

    current_est_idx: int | None = None
    current_employee: EmployeeBlock | None = None
    current_s54_group: list[DSNRecord] | None = None

    def _flush_employee() -> None:
        nonlocal current_employee
        if current_employee is None:
            return
        if current_employee.establishment_index is not None:
            establishments[current_employee.establishment_index].employee_blocks.append(
                current_employee
            )
        else:
            unassigned_employees.append(current_employee)
            warnings.append(
                f"Employee block starting at line {current_employee.records[0].line_number} "
                f"is not assigned to any establishment"
            )
        current_employee = None

    def _flush_s54_group() -> None:
        nonlocal current_s54_group
        if current_s54_group is None:
            return
        if current_est_idx is not None:
            establishments[current_est_idx].s54_blocks.append(current_s54_group)
        else:
            unassigned_s54.append(current_s54_group)
            warnings.append(
                f"S54 block starting at line {current_s54_group[0].line_number} "
                f"is not assigned to any establishment"
            )
        current_s54_group = None

    for record in records:
        code = record.code

        # 1. File-level records
        if any(code.startswith(p) for p in FILE_LEVEL_PREFIXES):
            _flush_employee()
            _flush_s54_group()
            file_level.append(record)
            continue

        # 2. Establishment boundary — S21.G00.06.001
        if code == ESTABLISHMENT_DECL_CODE:
            _flush_employee()
            _flush_s54_group()
            establishments.append(EstablishmentBlock(records=[record]))
            current_est_idx = len(establishments) - 1
            continue

        # 2. Establishment boundary — S21.G00.11.001
        if code == ESTABLISHMENT_IDENTITY_CODE:
            _flush_employee()
            _flush_s54_group()
            if current_est_idx is not None and not any(
                r.code == ESTABLISHMENT_IDENTITY_CODE
                for r in establishments[current_est_idx].records
            ):
                # Fold into existing establishment started by S21.G00.06
                establishments[current_est_idx].records.append(record)
            else:
                # No preceding S21.G00.06, or current establishment already has identity
                establishments.append(EstablishmentBlock(records=[record]))
                current_est_idx = len(establishments) - 1
            continue

        # 3. Other establishment header records
        if code.startswith("S21.G00.06.") or code.startswith("S21.G00.11."):
            if current_est_idx is not None:
                establishments[current_est_idx].records.append(record)
            else:
                warnings.append(
                    f"Line {record.line_number}: establishment record '{code}' "
                    f"before any establishment context"
                )
                file_level.append(record)
            continue

        # 4. Employee boundary
        if code == EMPLOYEE_START_CODE:
            _flush_employee()
            _flush_s54_group()
            current_employee = EmployeeBlock(
                records=[record],
                establishment_index=current_est_idx,
            )
            continue

        # 5. S54 amount blocks
        #
        # In the project fixtures, S54 blocks live at establishment level.
        # In real DSNs, they can also appear mid-employee without ending the
        # surrounding employee context. We therefore group S54 separately
        # without flushing the active employee.
        if code.startswith(S54_PREFIX):
            if code == "S21.G00.54.001":
                _flush_s54_group()
                current_s54_group = [record]
            elif current_s54_group is not None:
                current_s54_group.append(record)
            else:
                # Orphan S54 continuation record without a .001 start
                current_s54_group = [record]
            continue

        # 6. All other S21 records
        if code.startswith("S21."):
            if current_employee is not None:
                current_employee.records.append(record)
            elif current_est_idx is not None:
                establishments[current_est_idx].records.append(record)
            else:
                warnings.append(
                    f"Line {record.line_number}: record '{code}' "
                    f"appears before any establishment context"
                )
            continue

    # EOF flush
    _flush_employee()
    _flush_s54_group()

    return ParsedDSN(
        all_records=records,
        file_level_records=file_level,
        establishments=establishments,
        unassigned_employee_blocks=unassigned_employees,
        unassigned_s54_blocks=unassigned_s54,
        warnings=warnings,
        skipped_lines=skipped_lines,
    )


def parse(text: str) -> ParsedDSN:
    """Parse DSN text and segment into structured blocks."""
    records, skipped = parse_lines(text)
    return segment(records, skipped)
