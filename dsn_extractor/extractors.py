"""Metric extraction functions for DSN files."""

from __future__ import annotations

import datetime
from decimal import Decimal

from dsn_extractor.enums import (
    ABSENCE_MOTIF_LABELS,
    CONTRACT_END_REASON_LABELS,
    CONTRACT_NATURE_LABELS,
    RETIREMENT_CATEGORY_LABELS,
)
from dsn_extractor.contributions import (
    compute_contribution_comparisons,
    merge_contribution_comparisons,
)
from dsn_extractor.models import (
    Company,
    ContributionComparisons,
    Declaration,
    DSNOutput,
    Establishment,
    EstablishmentAmounts,
    EstablishmentCounts,
    EstablishmentExtras,
    EstablishmentIdentity,
    AbsenceDetail,
    PayrollTracking,
    Quality,
    SocialAnalysis,
)
from dsn_extractor.normalize import lookup_enum_label, normalize_date, normalize_decimal, normalize_empty
from dsn_extractor.parser import DSNRecord, EmployeeBlock, EstablishmentBlock, ParsedDSN


# ---------------------------------------------------------------------------
# Record lookup helpers
# ---------------------------------------------------------------------------


def _find_value(records: list[DSNRecord], code: str) -> str | None:
    """Return the raw_value of the first record matching *code*, or None."""
    for r in records:
        if r.code == code:
            return r.raw_value
    return None


def _find_all_values(records: list[DSNRecord], code: str) -> list[str]:
    """Return all raw_values for records matching *code*."""
    return [r.raw_value for r in records if r.code == code]


# ---------------------------------------------------------------------------
# Null-safe decimal helpers
# ---------------------------------------------------------------------------


def _sum_decimal(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    if a is None and b is None:
        return None
    return (a or Decimal(0)) + (b or Decimal(0))


# ---------------------------------------------------------------------------
# Employee name helper
# ---------------------------------------------------------------------------


def _employee_display_name(emp: EmployeeBlock) -> str:
    """Format employee name as 'NOM Prénom' from DSN fields.

    Uses S21.G00.30.002 (nom de famille) and S21.G00.30.004 (prénoms).
    Never reads S21.G00.30.001 (NIR) or S21.G00.30.018 (NTT).
    """
    nom = (_find_value(emp.records, "S21.G00.30.002") or "").strip()
    prenom = (_find_value(emp.records, "S21.G00.30.004") or "").strip()
    if nom and prenom:
        return f"{nom} {prenom}"
    if nom:
        return nom
    if prenom:
        return prenom
    return "?"


# ---------------------------------------------------------------------------
# Extraction functions
# ---------------------------------------------------------------------------


def _extract_declaration(file_level_records: list[DSNRecord]) -> Declaration:
    period_start = normalize_date(_find_value(file_level_records, "S20.G00.05.005") or "")
    period_end = normalize_date(_find_value(file_level_records, "S20.G00.05.007") or "")
    month = period_start.strftime("%Y-%m") if period_start else None

    return Declaration(
        norm_version=normalize_empty(_find_value(file_level_records, "S10.G00.00.001") or ""),
        declaration_nature_code=normalize_empty(_find_value(file_level_records, "S20.G00.05.001") or ""),
        declaration_kind_code=normalize_empty(_find_value(file_level_records, "S20.G00.05.002") or ""),
        declaration_rank_code=normalize_empty(_find_value(file_level_records, "S20.G00.05.003") or ""),
        period_start=period_start,
        period_end=period_end,
        month=month,
        dsn_id=normalize_empty(_find_value(file_level_records, "S20.G00.05.009") or ""),
    )


def _extract_company(file_level_records: list[DSNRecord]) -> Company:
    siren = normalize_empty(_find_value(file_level_records, "S10.G00.01.001") or "")
    nic = normalize_empty(_find_value(file_level_records, "S10.G00.01.002") or "")
    siret = siren + nic if (siren and nic) else None

    return Company(
        siren=siren,
        nic=nic,
        siret=siret,
        name=normalize_empty(_find_value(file_level_records, "S10.G00.01.003") or ""),
        address=normalize_empty(_find_value(file_level_records, "S10.G00.01.004") or ""),
        postal_code=normalize_empty(_find_value(file_level_records, "S10.G00.01.005") or ""),
        city=normalize_empty(_find_value(file_level_records, "S10.G00.01.006") or ""),
        country_code=normalize_empty(_find_value(file_level_records, "S10.G00.01.007") or ""),
    )


def _extract_establishment_identity(
    est: EstablishmentBlock,
    company_siren: str | None,
    employee_blocks: list[EmployeeBlock],
    warnings: list[str],
) -> EstablishmentIdentity:
    has_s11 = any(r.code == "S21.G00.11.001" for r in est.records)

    if has_s11:
        nic = normalize_empty(_find_value(est.records, "S21.G00.11.001") or "")
        naf_code = normalize_empty(_find_value(est.records, "S21.G00.11.002") or "")
        address = normalize_empty(_find_value(est.records, "S21.G00.11.003") or "")
        postal_code = normalize_empty(_find_value(est.records, "S21.G00.11.004") or "")
        city = normalize_empty(_find_value(est.records, "S21.G00.11.005") or "")
        name = normalize_empty(_find_value(est.records, "S21.G00.11.008") or "")
        ccn_code = normalize_empty(_find_value(est.records, "S21.G00.11.022") or "")
    else:
        nic = normalize_empty(_find_value(est.records, "S21.G00.06.001") or "")
        naf_code = None
        address = None
        postal_code = None
        city = None
        name = None
        ccn_code = None
        warnings.append("Establishment missing S21.G00.11 block, falling back to S21.G00.06")

    # CCN fallback from employee-level S21.G00.40.017
    if ccn_code is None:
        employee_ccns: set[str] = set()
        for emp in employee_blocks:
            val = _find_value(emp.records, "S21.G00.40.017")
            if val and val.strip():
                employee_ccns.add(val)
        if len(employee_ccns) == 1:
            ccn_code = employee_ccns.pop()
        elif len(employee_ccns) > 1:
            warnings.append(
                f"Conflicting employee CCN values: {sorted(employee_ccns)}"
            )

    siret = company_siren + nic if (company_siren and nic) else None

    return EstablishmentIdentity(
        nic=nic,
        siret=siret,
        name=name,
        naf_code=naf_code,
        ccn_code=ccn_code,
        address=address,
        postal_code=postal_code,
        city=city,
    )


def _extract_counts(
    employee_blocks: list[EmployeeBlock],
    period_start: datetime.date | None,
    period_end: datetime.date | None,
    warnings: list[str],
) -> EstablishmentCounts:
    by_retirement_code: dict[str, int] = {}
    by_retirement_label: dict[str, int] = {}
    by_conventional_status: dict[str, int] = {}
    by_contract_nature: dict[str, int] = {}
    by_contract_nature_label: dict[str, int] = {}
    exit_reasons_by_code: dict[str, int] = {}
    exit_reasons_by_label: dict[str, int] = {}
    absences_by_code: dict[str, int] = {}
    absences_employees_count = 0
    absences_events_count = 0
    stagiaires = 0
    new_employees = 0
    exiting_employees = 0
    entry_names: list[str] = []
    exit_names: list[str] = []
    absence_details: list[AbsenceDetail] = []

    for emp in employee_blocks:
        display_name = _employee_display_name(emp)
        # Contract nature
        nature_raw = _find_value(emp.records, "S21.G00.40.007")
        if nature_raw:
            by_contract_nature[nature_raw] = by_contract_nature.get(nature_raw, 0) + 1
            nature_label, was_known = lookup_enum_label(nature_raw, CONTRACT_NATURE_LABELS)
            by_contract_nature_label[nature_label] = (
                by_contract_nature_label.get(nature_label, 0) + 1
            )
            if nature_raw == "29":
                stagiaires += 1
            if not was_known:
                warnings.append(f"Unknown contract nature code: {nature_raw!r}")

        # Retirement category
        ret_raw = _find_value(emp.records, "S21.G00.40.003")
        if ret_raw:
            by_retirement_code[ret_raw] = by_retirement_code.get(ret_raw, 0) + 1
            label, was_known = lookup_enum_label(ret_raw, RETIREMENT_CATEGORY_LABELS)
            by_retirement_label[label] = by_retirement_label.get(label, 0) + 1
            if not was_known:
                warnings.append(f"Unknown retirement category code: {ret_raw!r}")

        # Conventional status
        conv_raw = _find_value(emp.records, "S21.G00.40.002")
        if conv_raw:
            by_conventional_status[conv_raw] = by_conventional_status.get(conv_raw, 0) + 1

        # New employees
        contract_start_raw = _find_value(emp.records, "S21.G00.40.001")
        if contract_start_raw:
            contract_start = normalize_date(contract_start_raw)
            if contract_start and period_start and period_end:
                if period_start <= contract_start <= period_end:
                    new_employees += 1
                    entry_names.append(display_name)
        else:
            warnings.append("Employee block missing contract start date (S21.G00.40.001)")

        # Exiting employees + exit reason aggregation
        end_date_raw = _find_value(emp.records, "S21.G00.62.001")
        if end_date_raw:
            end_date = normalize_date(end_date_raw)
            rupture_code = _find_value(emp.records, "S21.G00.62.002")
            if rupture_code is None:
                warnings.append(
                    "Contract end block (S21.G00.62) missing rupture code (S21.G00.62.002)"
                )
            if end_date and period_start and period_end:
                if period_start <= end_date <= period_end:
                    if rupture_code != "099":
                        exiting_employees += 1
                        exit_names.append(display_name)
                    # Aggregate exit reason for in-period exits
                    if rupture_code is not None:
                        exit_reasons_by_code[rupture_code] = (
                            exit_reasons_by_code.get(rupture_code, 0) + 1
                        )
                        reason_label, was_known = lookup_enum_label(
                            rupture_code, CONTRACT_END_REASON_LABELS
                        )
                        exit_reasons_by_label[reason_label] = (
                            exit_reasons_by_label.get(reason_label, 0) + 1
                        )
                        if not was_known:
                            warnings.append(
                                f"Unknown contract end reason code: {rupture_code!r}"
                            )

        # Absences / suspensions (S21.G00.65.001)
        absence_motifs = _find_all_values(emp.records, "S21.G00.65.001")
        if absence_motifs:
            absences_employees_count += 1
            absences_events_count += len(absence_motifs)
            for motif_code in absence_motifs:
                motif_label, _ = lookup_enum_label(motif_code, ABSENCE_MOTIF_LABELS)
                absence_details.append(AbsenceDetail(
                    employee_name=display_name,
                    motif_code=motif_code,
                    motif_label=motif_label,
                ))
                absences_by_code[motif_code] = absences_by_code.get(motif_code, 0) + 1
                _, was_known = lookup_enum_label(motif_code, ABSENCE_MOTIF_LABELS)
                if not was_known:
                    warnings.append(f"Unknown absence motif code: {motif_code!r}")

    return EstablishmentCounts(
        employee_blocks_count=len(employee_blocks),
        stagiaires=stagiaires,
        employees_by_retirement_category_code=by_retirement_code,
        employees_by_retirement_category_label=by_retirement_label,
        employees_by_conventional_status_code=by_conventional_status,
        employees_by_contract_nature_code=by_contract_nature,
        employees_by_contract_nature_label=by_contract_nature_label,
        new_employees_in_month=new_employees,
        exiting_employees_in_month=exiting_employees,
        exit_reasons_by_code=exit_reasons_by_code,
        exit_reasons_by_label=exit_reasons_by_label,
        absences_employees_count=absences_employees_count,
        absences_events_count=absences_events_count,
        absences_by_code=absences_by_code,
        entry_employee_names=entry_names,
        exit_employee_names=exit_names,
        absence_event_details=absence_details,
    )


def _extract_amounts(
    s54_blocks: list[list[DSNRecord]],
    warnings: list[str],
) -> EstablishmentAmounts:
    if not s54_blocks:
        warnings.append("No S21.G00.54 block family present in establishment")
        return EstablishmentAmounts()

    type_17: Decimal | None = None
    type_18: Decimal | None = None
    type_19: Decimal | None = None

    for group in s54_blocks:
        s54_type = _find_value(group, "S21.G00.54.001")
        amount = normalize_decimal(_find_value(group, "S21.G00.54.002") or "")
        if amount is None:
            continue
        if s54_type == "17":
            type_17 = (type_17 or Decimal(0)) + amount
        elif s54_type == "18":
            type_18 = (type_18 or Decimal(0)) + amount
        elif s54_type == "19":
            type_19 = (type_19 or Decimal(0)) + amount

    return EstablishmentAmounts(
        tickets_restaurant_employer_contribution_total=type_17,
        transport_public_total=type_18,
        transport_personal_total=type_19,
    )


def _extract_extras(employee_blocks: list[EmployeeBlock]) -> EstablishmentExtras:
    net_fiscal: Decimal | None = None
    net_paid: Decimal | None = None
    pas: Decimal | None = None

    for emp in employee_blocks:
        nf = normalize_decimal(_find_value(emp.records, "S21.G00.50.002") or "")
        if nf is not None:
            net_fiscal = (net_fiscal or Decimal(0)) + nf

        np_ = normalize_decimal(_find_value(emp.records, "S21.G00.50.004") or "")
        if np_ is not None:
            net_paid = (net_paid or Decimal(0)) + np_

        ps = normalize_decimal(_find_value(emp.records, "S21.G00.50.009") or "")
        if ps is not None:
            pas = (pas or Decimal(0)) + ps

    return EstablishmentExtras(
        net_fiscal_sum=net_fiscal,
        net_paid_sum=net_paid,
        pas_sum=pas,
    )


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------


def _merge_dict(target: dict[str, int], source: dict[str, int]) -> None:
    """Merge source dict into target by summing values per key."""
    for k, v in source.items():
        target[k] = target.get(k, 0) + v


def _merge_counts(counts_list: list[EstablishmentCounts]) -> EstablishmentCounts:
    total = EstablishmentCounts()
    for c in counts_list:
        total.employee_blocks_count += c.employee_blocks_count
        total.stagiaires += c.stagiaires
        total.new_employees_in_month += c.new_employees_in_month
        total.exiting_employees_in_month += c.exiting_employees_in_month
        total.absences_employees_count += c.absences_employees_count
        total.absences_events_count += c.absences_events_count
        _merge_dict(total.employees_by_retirement_category_code, c.employees_by_retirement_category_code)
        _merge_dict(total.employees_by_retirement_category_label, c.employees_by_retirement_category_label)
        _merge_dict(total.employees_by_conventional_status_code, c.employees_by_conventional_status_code)
        _merge_dict(total.employees_by_contract_nature_code, c.employees_by_contract_nature_code)
        _merge_dict(total.employees_by_contract_nature_label, c.employees_by_contract_nature_label)
        _merge_dict(total.exit_reasons_by_code, c.exit_reasons_by_code)
        _merge_dict(total.exit_reasons_by_label, c.exit_reasons_by_label)
        _merge_dict(total.absences_by_code, c.absences_by_code)
        total.entry_employee_names += c.entry_employee_names
        total.exit_employee_names += c.exit_employee_names
        total.absence_event_details += [d.model_copy() for d in c.absence_event_details]
    return total


def _merge_amounts(amounts_list: list[EstablishmentAmounts]) -> EstablishmentAmounts:
    total = EstablishmentAmounts()
    for a in amounts_list:
        total.tickets_restaurant_employer_contribution_total = _sum_decimal(
            total.tickets_restaurant_employer_contribution_total,
            a.tickets_restaurant_employer_contribution_total,
        )
        total.transport_public_total = _sum_decimal(
            total.transport_public_total, a.transport_public_total
        )
        total.transport_personal_total = _sum_decimal(
            total.transport_personal_total, a.transport_personal_total
        )
    return total


def _merge_extras(extras_list: list[EstablishmentExtras]) -> EstablishmentExtras:
    total = EstablishmentExtras()
    for e in extras_list:
        total.net_fiscal_sum = _sum_decimal(total.net_fiscal_sum, e.net_fiscal_sum)
        total.net_paid_sum = _sum_decimal(total.net_paid_sum, e.net_paid_sum)
        total.pas_sum = _sum_decimal(total.pas_sum, e.pas_sum)
        total.gross_sum_from_salary_bases = _sum_decimal(
            total.gross_sum_from_salary_bases, e.gross_sum_from_salary_bases
        )
    return total


# ---------------------------------------------------------------------------
# Composition helpers
# ---------------------------------------------------------------------------


# Complexity score weights — additive workload indicator, not billing.
_COMPLEXITY_WEIGHTS = {
    "bulletins": 1,
    "entries": 3,
    "exits": 3,
    "absence_events": 2,
    "dsn_anomalies": 5,
}


def _compose_social_analysis(
    counts: EstablishmentCounts,
    extras: EstablishmentExtras,
    quality: Quality,
) -> SocialAnalysis:
    ret_labels = counts.employees_by_retirement_category_label
    cadre = ret_labels.get("cadre", 0) + ret_labels.get("extension_cadre", 0)
    non_cadre = ret_labels.get("non_cadre", 0)

    return SocialAnalysis(
        effectif=counts.employee_blocks_count,
        entrees=counts.new_employees_in_month,
        sorties=counts.exiting_employees_in_month,
        stagiaires=counts.stagiaires,
        cadre_count=cadre,
        non_cadre_count=non_cadre,
        contracts_by_code=dict(counts.employees_by_contract_nature_code),
        contracts_by_label=dict(counts.employees_by_contract_nature_label),
        exit_reasons_by_code=dict(counts.exit_reasons_by_code),
        exit_reasons_by_label=dict(counts.exit_reasons_by_label),
        absences_employees_count=counts.absences_employees_count,
        absences_events_count=counts.absences_events_count,
        absences_by_code=dict(counts.absences_by_code),
        net_verse_total=extras.net_paid_sum,
        net_fiscal_total=extras.net_fiscal_sum,
        pas_total=extras.pas_sum,
        quality_alerts_count=len(quality.warnings),
        quality_alerts=list(quality.warnings),
    )


def _compose_payroll_tracking(
    counts: EstablishmentCounts,
    quality: Quality,
) -> PayrollTracking:
    bulletins = counts.employee_blocks_count
    entries = counts.new_employees_in_month
    exits = counts.exiting_employees_in_month
    absence_events = counts.absences_events_count
    anomalies = len(quality.warnings)

    exceptional = exits + absence_events

    inputs = {
        "bulletins": bulletins,
        "entries": entries,
        "exits": exits,
        "absence_events": absence_events,
        "dsn_anomalies": anomalies,
    }
    score = sum(inputs[k] * _COMPLEXITY_WEIGHTS[k] for k in _COMPLEXITY_WEIGHTS)

    return PayrollTracking(
        bulletins=bulletins,
        billable_entries=entries,
        billable_exits=exits,
        billable_absence_events=absence_events,
        exceptional_events_count=exceptional,
        dsn_anomalies_count=anomalies,
        complexity_score=score,
        complexity_inputs=inputs,
        billable_entry_names=list(counts.entry_employee_names),
        billable_exit_names=list(counts.exit_employee_names),
        billable_absence_details=[d.model_copy() for d in counts.absence_event_details],
    )


# ---------------------------------------------------------------------------
# Public orchestrator
# ---------------------------------------------------------------------------


def extract(parsed: ParsedDSN, source_file: str = "") -> DSNOutput:
    """Extract structured metrics from a parsed DSN file."""
    global_warnings: list[str] = []

    # 1. Declaration
    declaration = _extract_declaration(parsed.file_level_records)
    period_start = declaration.period_start
    period_end = declaration.period_end

    if period_start is None:
        global_warnings.append("Missing or invalid period start date (S20.G00.05.005)")
    if period_end is None:
        global_warnings.append("Missing or invalid period end date (S20.G00.05.007)")

    # 2. Company
    company = _extract_company(parsed.file_level_records)

    # 3. Multiple establishments warning
    if len(parsed.establishments) > 1:
        global_warnings.append("Multiple establishments detected in file")

    # 4. Per-establishment extraction
    establishments: list[Establishment] = []
    all_counts: list[EstablishmentCounts] = []
    all_amounts: list[EstablishmentAmounts] = []
    all_extras: list[EstablishmentExtras] = []
    all_contribution_comparisons: list[ContributionComparisons] = []

    for est_block in parsed.establishments:
        est_warnings: list[str] = []

        identity = _extract_establishment_identity(
            est_block, company.siren, est_block.employee_blocks, est_warnings
        )
        counts = _extract_counts(
            est_block.employee_blocks, period_start, period_end, est_warnings
        )
        amounts = _extract_amounts(est_block.s54_blocks, est_warnings)
        extras = _extract_extras(est_block.employee_blocks)
        contribution_comparisons = compute_contribution_comparisons(
            est_block,
            reference_date=period_start,
        )

        est_quality = Quality(warnings=est_warnings)
        est = Establishment(
            identity=identity,
            counts=counts,
            amounts=amounts,
            extras=extras,
            quality=est_quality,
            social_analysis=_compose_social_analysis(counts, extras, est_quality),
            payroll_tracking=_compose_payroll_tracking(counts, est_quality),
            contribution_comparisons=contribution_comparisons,
        )
        establishments.append(est)
        all_counts.append(counts)
        all_amounts.append(amounts)
        all_extras.append(extras)
        all_contribution_comparisons.append(contribution_comparisons)

    # 5. Global aggregation
    global_counts = _merge_counts(all_counts)
    global_amounts = _merge_amounts(all_amounts)
    global_extras = _merge_extras(all_extras)
    global_contribution_comparisons = merge_contribution_comparisons(
        all_contribution_comparisons
    )

    # 6. Global quality: parser warnings + orchestrator warnings + per-establishment warnings
    all_warnings = list(parsed.warnings) + global_warnings
    for est in establishments:
        all_warnings.extend(est.quality.warnings)

    global_quality = Quality(warnings=all_warnings)

    return DSNOutput(
        source_file=source_file,
        declaration=declaration,
        company=company,
        establishments=establishments,
        global_counts=global_counts,
        global_amounts=global_amounts,
        global_extras=global_extras,
        global_quality=global_quality,
        global_social_analysis=_compose_social_analysis(
            global_counts, global_extras, global_quality
        ),
        global_payroll_tracking=_compose_payroll_tracking(global_counts, global_quality),
        global_contribution_comparisons=global_contribution_comparisons,
    )
