"""Pydantic output models for DSN extraction."""

from __future__ import annotations

import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Declaration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    norm_version: str | None = None
    declaration_nature_code: str | None = None
    declaration_kind_code: str | None = None
    declaration_rank_code: str | None = None
    period_start: datetime.date | None = None
    period_end: datetime.date | None = None
    month: str | None = None  # YYYY-MM derived from period_start
    dsn_id: str | None = None

    @field_validator("month")
    @classmethod
    def _month_must_be_yyyy_mm(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError("month must be a string in YYYY-MM format")
        import re
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", v):
            raise ValueError(f"month must match YYYY-MM format, got {v!r}")
        return v


class Company(BaseModel):
    model_config = ConfigDict(extra="forbid")

    siren: str | None = None
    nic: str | None = None
    siret: str | None = None  # siren + nic, computed by extractor
    name: str | None = None
    address: str | None = None
    postal_code: str | None = None
    city: str | None = None
    country_code: str | None = None


class EstablishmentIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nic: str | None = None
    siret: str | None = None  # company siren + establishment nic
    name: str | None = None
    naf_code: str | None = None
    ccn_code: str | None = None
    address: str | None = None
    postal_code: str | None = None
    city: str | None = None
    employee_band_code: str | None = None


class EstablishmentCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    employee_blocks_count: int = 0
    stagiaires: int = 0
    employees_by_retirement_category_code: dict[str, int] = Field(default_factory=dict)
    employees_by_retirement_category_label: dict[str, int] = Field(default_factory=dict)
    employees_by_conventional_status_code: dict[str, int] = Field(default_factory=dict)
    employees_by_contract_nature_code: dict[str, int] = Field(default_factory=dict)
    employees_by_contract_nature_label: dict[str, int] = Field(default_factory=dict)
    new_employees_in_month: int = 0
    exiting_employees_in_month: int = 0
    exit_reasons_by_code: dict[str, int] = Field(default_factory=dict)
    exit_reasons_by_label: dict[str, int] = Field(default_factory=dict)
    absences_employees_count: int = 0
    absences_events_count: int = 0
    absences_by_code: dict[str, int] = Field(default_factory=dict)
    entry_employee_names: list[str] = Field(default_factory=list)
    exit_employee_names: list[str] = Field(default_factory=list)
    absence_event_details: list[AbsenceDetail] = Field(default_factory=list)


class EstablishmentAmounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tickets_restaurant_employer_contribution_total: Decimal | None = None
    transport_public_total: Decimal | None = None
    transport_personal_total: Decimal | None = None


class EstablishmentExtras(BaseModel):
    model_config = ConfigDict(extra="forbid")

    net_fiscal_sum: Decimal | None = None
    net_paid_sum: Decimal | None = None
    pas_sum: Decimal | None = None
    gross_sum_from_salary_bases: Decimal | None = None


class AbsenceDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    employee_name: str
    motif_code: str
    motif_label: str


class Quality(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warnings: list[str] = Field(default_factory=list)


class SocialAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effectif: int = 0
    entrees: int = 0
    sorties: int = 0
    stagiaires: int = 0
    cadre_count: int = 0
    non_cadre_count: int = 0
    contracts_by_code: dict[str, int] = Field(default_factory=dict)
    contracts_by_label: dict[str, int] = Field(default_factory=dict)
    exit_reasons_by_code: dict[str, int] = Field(default_factory=dict)
    exit_reasons_by_label: dict[str, int] = Field(default_factory=dict)
    absences_employees_count: int = 0
    absences_events_count: int = 0
    absences_by_code: dict[str, int] = Field(default_factory=dict)
    net_verse_total: Decimal | None = None
    net_fiscal_total: Decimal | None = None
    pas_total: Decimal | None = None
    quality_alerts_count: int = 0
    quality_alerts: list[str] = Field(default_factory=list)


class PayrollTracking(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bulletins: int = 0
    billable_entries: int = 0
    billable_exits: int = 0
    billable_absence_events: int = 0
    exceptional_events_count: int = 0
    dsn_anomalies_count: int = 0
    complexity_score: int = 0
    complexity_inputs: dict[str, int] = Field(default_factory=dict)
    billable_entry_names: list[str] = Field(default_factory=list)
    billable_exit_names: list[str] = Field(default_factory=list)
    billable_absence_details: list[AbsenceDetail] = Field(default_factory=list)


class ContributionComparisonDetail(BaseModel):
    """Detail line in a contribution reconciliation (CTP, employee, contract...)."""

    model_config = ConfigDict(extra="forbid")

    key: str
    label: str | None = None
    short_label: str | None = None
    ctp_code: str | None = None
    mapped_code: str | None = None
    assiette_qualifier: str | None = None
    assiette_label: str | None = None
    rate: Decimal | None = None
    expected_rate: Decimal | None = None
    base_amount: Decimal | None = None
    declared_amount: Decimal | None = None
    computed_amount: Decimal | None = None
    delta: Decimal | None = None
    status: str = "ok"
    rate_mismatch: bool = False
    amount_mismatch: bool = False
    record_lines: list[int] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class EmployeeContributionBreakdown(BaseModel):
    """One employee's contribution to a single individual code (S21.G00.81.001).

    Amounts are summed across all S81 rows for the same (employee, code) pair
    so repeated rows (e.g. regularisations within the same month) collapse to
    one line. Line references accumulate across the collapsed rows.
    """

    model_config = ConfigDict(extra="forbid")

    employee_name: str
    individual_code: str | None = None  # S21.G00.81.001 (first code, backward compat)
    individual_codes: list[str] = Field(default_factory=list)
    amount: Decimal
    record_lines: list[int] = Field(default_factory=list)


class UrssafCodeBreakdown(BaseModel):
    """Per-CTP drill-down from establishment-level code to employee-level amounts.

    Populated only for URSSAF items. One row per distinct CTP code found in
    S23 (i.e. assiette variants of the same CTP collapse into one breakdown).

    ``mapping_status`` values:
        - ``rattachable``       : CTP is in the Slice B mapping table and at
                                  least one matching S81 row was found.
        - ``non_rattache``      : CTP is not in the mapping table. Default-deny.
                                  No drill-down attempted.
        - ``manquant_individuel``: CTP is mappable but no matching S81 rows
                                   were found in the employee blocks.
    """

    model_config = ConfigDict(extra="forbid")

    ctp_code: str
    ctp_label: str | None = None
    mapped_code: str | None = None  # Displayed code (e.g. "100D", "100P"); falls back to ctp_code
    individual_code: str | None = None  # Mapped S21.G00.81.001 code, when known
    mapping_status: str = "non_rattache"
    mapping_reason: str | None = None
    applied_individual_codes: list[str] = Field(default_factory=list)
    excluded_individual_codes: list[dict] = Field(default_factory=list)
    declared_amount: Decimal | None = None  # Sum of CTP amounts across assiette variants
    individual_amount: Decimal | None = None  # Sum of S81.004 across employees
    delta: Decimal | None = None  # declared_amount - individual_amount (signed, for audit)
    delta_within_unit: bool = False  # True when abs(delta) < 1.00€ (URSSAF row policy)
    display_absolute: bool = False  # UI renders abs() of amounts and abs-based delta
    employees: list[EmployeeContributionBreakdown] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ContributionComparisonItem(BaseModel):
    """A reconciliation for one organism in one family."""

    model_config = ConfigDict(extra="forbid")

    family: str  # urssaf | pas | prevoyance | mutuelle | retraite | unclassified
    organism_id: str | None = None
    organism_label: str | None = None
    aggregate_amount: Decimal | None = None
    bordereau_amount: Decimal | None = None
    component_amount: Decimal | None = None
    individual_amount: Decimal | None = None
    aggregate_vs_bordereau_delta: Decimal | None = None
    bordereau_vs_component_delta: Decimal | None = None
    aggregate_vs_component_delta: Decimal | None = None
    aggregate_vs_individual_delta: Decimal | None = None
    status: str = "ok"
    details: list[ContributionComparisonDetail] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    adhesion_id: str | None = None
    contract_ref: str | None = None
    # Slice C: URSSAF per-CTP drill-down to employee-level amounts.
    # Empty for non-URSSAF families. Empty for URSSAF items when no S23
    # details are present or when every CTP is non_rattache with no S78/S81.
    urssaf_code_breakdowns: list[UrssafCodeBreakdown] = Field(default_factory=list)


class ContributionComparisons(BaseModel):
    """Collection of all reconciliations for an establishment or global."""

    model_config = ConfigDict(extra="forbid")

    items: list[ContributionComparisonItem] = Field(default_factory=list)
    ok_count: int = 0
    mismatch_count: int = 0
    warning_count: int = 0


class Establishment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity: EstablishmentIdentity = Field(default_factory=EstablishmentIdentity)
    counts: EstablishmentCounts = Field(default_factory=EstablishmentCounts)
    amounts: EstablishmentAmounts = Field(default_factory=EstablishmentAmounts)
    extras: EstablishmentExtras = Field(default_factory=EstablishmentExtras)
    quality: Quality = Field(default_factory=Quality)
    social_analysis: SocialAnalysis = Field(default_factory=SocialAnalysis)
    payroll_tracking: PayrollTracking = Field(default_factory=PayrollTracking)
    contribution_comparisons: ContributionComparisons = Field(
        default_factory=ContributionComparisons
    )


class DSNOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_file: str = ""
    declaration: Declaration = Field(default_factory=Declaration)
    company: Company = Field(default_factory=Company)
    establishments: list[Establishment] = Field(default_factory=list)
    global_counts: EstablishmentCounts = Field(default_factory=EstablishmentCounts)
    global_amounts: EstablishmentAmounts = Field(default_factory=EstablishmentAmounts)
    global_extras: EstablishmentExtras = Field(default_factory=EstablishmentExtras)
    global_quality: Quality = Field(default_factory=Quality)
    global_social_analysis: SocialAnalysis = Field(default_factory=SocialAnalysis)
    global_payroll_tracking: PayrollTracking = Field(default_factory=PayrollTracking)
    global_contribution_comparisons: ContributionComparisons = Field(
        default_factory=ContributionComparisons
    )
