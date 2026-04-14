"""Contribution reconciliation logic for DSN files.

Compares aggregate (S21.G00.20), detailed (S21.G00.22/23/55), and individual
(S21.G00.50/78/81) amounts across 5 families: PAS, URSSAF, prévoyance,
mutuelle, retraite.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from dsn_extractor.block_groups import (
    BlockGroup,
    EstablishmentBlockGroups,
    EmployeeBlockGroups,
    group_employee_blocks,
    group_establishment_blocks,
)
from dsn_extractor.ctp_rates import lookup_ctp_reference
from dsn_extractor.models import (
    ContributionComparisonDetail,
    ContributionComparisonItem,
    ContributionComparisons,
    EmployeeContributionBreakdown,
    UrssafCodeBreakdown,
)
from dsn_extractor.normalize import normalize_decimal
from dsn_extractor.organisms import (
    ORGANISM_REGISTRY,
    CTP_LABELS,
    lookup_complementary_family_override,
    lookup_organism,
    lookup_ctp,
)
from dsn_extractor.parser import DSNRecord, EmployeeBlock, EstablishmentBlock
from dsn_extractor.urssaf_mapping_rules import (
    get_rule,
    is_rule_active,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_value(records: list[DSNRecord], code: str) -> str | None:
    for r in records:
        if r.code == code:
            return r.raw_value
    return None


def _find_all_values(records: list[DSNRecord], code: str) -> list[str]:
    return [r.raw_value for r in records if r.code == code]


def _find_all_records(records: list[DSNRecord], code: str) -> list[DSNRecord]:
    return [r for r in records if r.code == code]


def _record_lines(records: list[DSNRecord]) -> list[int]:
    return [r.line_number for r in records]


def _dec(raw: str | None) -> Decimal | None:
    if raw is None:
        return None
    return normalize_decimal(raw)


def _within_tolerance(a: Decimal | None, b: Decimal | None, tol: Decimal) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


def _rounded_to_unit_ok(a: Decimal | None, b: Decimal | None) -> bool:
    """Return True if abs(a - b) rounds to 0 at the euro level.

    Used by non-URSSAF-per-code reconciliations (PAS status, Ctrl1/Ctrl2).
    URSSAF per-code rows use ``_urssaf_row_delta_within_unit`` instead, which
    implements the product-confirmed literal ``abs(delta) < 1.00€`` policy.
    """
    if a is None or b is None:
        return False
    return abs(a - b).quantize(Decimal("1"), rounding=ROUND_HALF_UP) == 0


_URSSAF_ROW_EUR_TOL = Decimal("1.00")


def _urssaf_row_delta_within_unit(a: Decimal | None, b: Decimal | None) -> bool:
    """URSSAF per-code tolerance — strict ``abs(a - b) < 1.00€``.

    Confirmed product policy for the per-CTP rattachement UX:
      - ``abs(delta) < 1.00€`` → row is OK (no badge, no filter surface).
      - ``abs(delta) >= 1.00€`` → row is an issue.

    Intentionally strict at the 1.00 boundary: a 1.00€ delta is surfaced so
    the payroll admin sees the drift. This replaces the prior
    ``_rounded_to_unit_ok`` behaviour, which rounded at half and therefore
    treated e.g. 0.74€ as an issue — rejected by product.
    """
    if a is None or b is None:
        return False
    return abs(a - b) < _URSSAF_ROW_EUR_TOL


REGULARIZATION_WARNING = (
    "Des régularisations DSN ont été détectées. Les éléments régularisés "
    "sur des mois précédents ne sont pas pris en compte correctement par "
    "cet outil en V1."
)

_TOL_001 = Decimal("0.01")
_RATE_TOL_0001 = Decimal("0.0001")

ASSIETTE_QUALIFIER_LABELS: dict[str, str] = {
    "920": "Taux déplafonné",
    "921": "Taux plafonné",
}

# DSN 13.3 defines these S21.G00.23 lines as carrying only the enterprise ATMP
# rate in .003 while leaving .005 empty. They must not be validated against the
# generic CTP reference rate or turned into a payable amount.
AT_RATE_ONLY_CTPS: set[tuple[str, str]] = {
    ("100", "920"),
    ("726", "920"),
    ("734", "920"),
    ("863", "920"),
}


def _employee_display_name(emp: EmployeeBlock) -> str:
    nom = (_find_value(emp.records, "S21.G00.30.002") or "").strip()
    prenom = (_find_value(emp.records, "S21.G00.30.004") or "").strip()
    if nom and prenom:
        return f"{nom} {prenom}"
    return nom or prenom or "?"


def _format_assiette_label(qualifier: str | None) -> str | None:
    if not qualifier:
        return None
    return ASSIETTE_QUALIFIER_LABELS.get(qualifier, qualifier)


def _is_at_rate_only_ctp(ctp_code: str, assiette_qualifier: str | None) -> bool:
    if not assiette_qualifier:
        return False
    return (ctp_code, assiette_qualifier) in AT_RATE_ONLY_CTPS


def _format_mapped_ctp_code(
    ctp_code: str,
    assiette_qualifier: str | None,
    has_plafonne_rate: bool,
    has_deplafonne_rate: bool,
) -> str:
    if assiette_qualifier == "921" and has_plafonne_rate:
        return f"{ctp_code}P"
    if assiette_qualifier == "920" and has_deplafonne_rate:
        return f"{ctp_code}D"
    return ctp_code


def _select_reference_rate(
    ctp_code: str,
    assiette_qualifier: str | None,
    reference_date: dt.date | None,
) -> tuple[str, str | None, str | None, str | None, Decimal | None]:
    ref = lookup_ctp_reference(ctp_code, reference_date)
    if ref is None:
        return ctp_code, None, None, None, None

    expected_rate: Decimal | None = None
    if assiette_qualifier == "921" and ref.rate_plafonne is not None:
        expected_rate = ref.rate_plafonne
    elif assiette_qualifier == "920" and ref.rate_deplafonne is not None:
        expected_rate = ref.rate_deplafonne
    elif ref.rate_deplafonne is not None and ref.rate_plafonne is None:
        expected_rate = ref.rate_deplafonne
    elif ref.rate_plafonne is not None and ref.rate_deplafonne is None:
        expected_rate = ref.rate_plafonne

    mapped_code = _format_mapped_ctp_code(
        ctp_code,
        assiette_qualifier,
        ref.rate_plafonne is not None,
        ref.rate_deplafonne is not None,
    )
    return mapped_code, ref.label, ref.short_label, ref.fmt, expected_rate


# ---------------------------------------------------------------------------
# Classification (rules 1→2→3→3b→4→5)
# ---------------------------------------------------------------------------


def _classify_s20(
    organism_id: str,
    s22_organism_ids: set[str],
    s15_organism_ids: set[str],
) -> str:
    """Return family string for an S20 block's organism_id."""
    # Rule 1: structural literal
    if organism_id == "DGFIP":
        return "pas"
    # Rule 2: structural S22 linkage
    if organism_id in s22_organism_ids:
        return "urssaf"
    # Rule 3: structural S15 linkage → complementary universe.
    # The business split mutuelle vs prevoyance is resolved later at the
    # contract level, not guessed here from the organism alone.
    if organism_id in s15_organism_ids:
        return "complementary"
    # Rule 4: registry fallback — only retraite (no structural aggregate path
    # exists for retraite complémentaire in the DSN data model)
    _, _, family = lookup_organism(organism_id)
    if family == "retraite":
        return "retraite"
    # Rule 5: unclassified — registry-only urssaf/pas/prevoyance/mutuelle
    # without their structural link (S22/S15/DGFIP) must NOT be classified
    return "unclassified"


# ---------------------------------------------------------------------------
# Regularization detection
# ---------------------------------------------------------------------------


def _check_regularization(block: BlockGroup) -> bool:
    """Check if a block contains a regularization marker."""
    for r in block.records:
        if r.code in ("S21.G00.20.013", "S21.G00.22.006", "S21.G00.55.005"):
            if r.raw_value and r.raw_value.strip():
                return True
    for child in block.children:
        if _check_regularization(child):
            return True
    return False


# ---------------------------------------------------------------------------
# PAS reconciliation
# ---------------------------------------------------------------------------


def _compute_pas(
    dgfip_s20_blocks: list[BlockGroup],
    employee_blocks: list[EmployeeBlock],
) -> ContributionComparisonItem:
    warnings: list[str] = []

    if len(dgfip_s20_blocks) > 1:
        warnings.append("multiple_dgfip_blocks")

    # Aggregate amount
    aggregate = Decimal(0)
    agg_lines: list[int] = []
    has_regularization = False
    for s20 in dgfip_s20_blocks:
        amt = _dec(_find_value(s20.records, "S21.G00.20.005"))
        if amt is not None:
            aggregate += amt
        agg_lines.extend(_record_lines(s20.records))
        if _check_regularization(s20):
            has_regularization = True

    # Individual amount: sum ALL S21.G00.50.009 across ALL employees
    individual = Decimal(0)
    details: list[ContributionComparisonDetail] = []
    has_individual = False
    for emp in employee_blocks:
        pas_records = _find_all_records(emp.records, "S21.G00.50.009")
        emp_total = Decimal(0)
        for rec in pas_records:
            val = _dec(rec.raw_value)
            if val is not None:
                emp_total += val
                has_individual = True
        if emp_total != 0:
            name = _employee_display_name(emp)
            details.append(ContributionComparisonDetail(
                key=name,
                label="PAS individuel",
                declared_amount=emp_total,
                status="ok",
                record_lines=[r.line_number for r in pas_records],
            ))
            individual += emp_total

    # Status
    aggregate_amount = aggregate if dgfip_s20_blocks else None
    individual_amount = individual if has_individual else None

    if aggregate_amount is None:
        status = "manquant_agrege"
    elif individual_amount is None:
        status = "manquant_individuel"
    elif _rounded_to_unit_ok(aggregate_amount, individual_amount):
        status = "ok"
    else:
        status = "ecart"

    delta = None
    if aggregate_amount is not None and individual_amount is not None:
        delta = aggregate_amount - individual_amount

    if has_regularization:
        warnings.append(REGULARIZATION_WARNING)

    return ContributionComparisonItem(
        family="pas",
        organism_id="DGFIP",
        organism_label="DGFIP",
        aggregate_amount=aggregate_amount,
        individual_amount=individual_amount,
        aggregate_vs_individual_delta=delta,
        status=status,
        details=details,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# URSSAF reconciliation
# ---------------------------------------------------------------------------


#: Per-CTP "incomplete collapse" warning — mirrors the item-level
#: "Sous-total CTP non affiché" message emitted by _compute_urssaf when
#: component_amount is hidden because at least one CTP is non_calculable.
#: Applied here at the per-CTP level when one assiette variant is calculable
#: and another is not, so the collapsed row never advertises a partial total.
_PARTIAL_CTP_WARNING = (
    "Sous-total CTP non affiché : au moins une variante d'assiette n'est "
    "pas calculable à partir de la DSN seule."
)


def _collect_employee_contract_natures(
    employee_blocks: list[EmployeeBlock],
) -> dict[int, frozenset[str]]:
    """Map employee index → set of S21.G00.40.007 contract nature values."""
    result: dict[int, frozenset[str]] = {}
    for idx, emp in enumerate(employee_blocks):
        natures = frozenset(
            v.strip() for v in _find_all_values(emp.records, "S21.G00.40.007")
            if v and v.strip()
        )
        result[idx] = natures
    return result


def _collect_s81_by_individual_code(
    employee_blocks: list[EmployeeBlock],
) -> tuple[dict[str, list[tuple[int, str, Decimal, list[int], str]]], bool]:
    """Scan employees once and bucket S81 amounts by individual code.

    Returns a tuple ``(by_code, has_any_s78_s81)`` where:
        - ``by_code`` maps ``S21.G00.81.001`` → list of
          ``(employee_index, employee_display_name, amount, record_lines,
          base_code_s78)`` tuples. ``employee_index`` is the stable
          position of the source block in ``employee_blocks`` and is used
          by the caller as the aggregation key so that two distinct
          employees sharing the same visible name (homonyms) are never
          collapsed into one row. ``base_code_s78`` is the parent S78
          base code (``S21.G00.78.001``) used for component-scoped
          matching. Multiple rows for the same (employee, code) pair are
          preserved as separate tuples; the caller is responsible for
          aggregation.
        - ``has_any_s78_s81`` is True when at least one S78 block exists in
          the scanned employees (used to decide whether to surface the
          "non_rattache despite individual data present" warning).
    """
    by_code: dict[str, list[tuple[int, str, Decimal, list[int], str]]] = {}
    has_any_s78_s81 = False

    for emp_idx, emp in enumerate(employee_blocks):
        emp_groups = group_employee_blocks(emp)
        if emp_groups.s78_blocks:
            has_any_s78_s81 = True
        emp_name = _employee_display_name(emp)

        for s78 in emp_groups.s78_blocks:
            base_code_78 = (_find_value(s78.records, "S21.G00.78.001") or "").strip()
            for s81 in s78.children:
                code_81 = (_find_value(s81.records, "S21.G00.81.001") or "").strip()
                if not code_81:
                    continue
                amt = _dec(_find_value(s81.records, "S21.G00.81.004"))
                if amt is None:
                    continue
                by_code.setdefault(code_81, []).append(
                    (emp_idx, emp_name, amt, _record_lines(s81.records), base_code_78)
                )

    return by_code, has_any_s78_s81


def _build_urssaf_code_breakdowns(
    details: list[ContributionComparisonDetail],
    s81_by_code: dict[str, list[tuple[int, str, Decimal, list[int], str]]],
    qualifiers_by_ctp: dict[str, set[str]],
    insee_codes_by_ctp: dict[str, set[str]],
    ctps_with_empty_qualifier: set[str] | None = None,
    contract_natures_by_emp: dict[int, frozenset[str]] | None = None,
) -> list[UrssafCodeBreakdown]:
    """Group URSSAF details by CTP code and attach employee drill-down.

    The breakdown is computed at CTP level (not per-assiette-variant) so that
    multi-assiette CTPs produce a single row whose declared amount is the sum
    across variants. The individual side is matched via the V1 rule engine
    (``dsn_extractor.urssaf_mapping_rules``) with a default-deny rule: unknown
    CTPs are reported as ``non_rattache`` without attempting any drill-down.

    For rules with ``components``, matching is qualifier-scoped: only components
    whose assiette qualifier was declared in the bordereau are activated, and
    S81 rows are filtered by the component's allowed base codes.

    Per-CTP completeness is tracked while collapsing: if any contributing
    detail row has no chosen amount (neither declared nor recomputed), the
    collapsed row's ``declared_amount`` is suppressed (set to ``None``) and
    a warning is attached so the UI never presents a partial sum as if it
    were the full per-code declared total.
    """
    # Row identity is (ctp_code, mapped_code) so mixed-qualifier CTPs (e.g.
    # 100 920/921 → 100D/100P) surface as distinct rows. ``mapped_code``
    # falls back to ``ctp_code`` for CTPs without a qualifier split, which
    # preserves byte-identical behaviour for single-qualifier rules.
    ordered_keys: list[tuple[str, str]] = []
    declared_by_row: dict[tuple[str, str], Decimal | None] = {}
    # Tracks only the raw declared amounts from S21.G00.23.005 (no computed
    # fallback). Used by sign-gated rules (668/669) which must read the
    # actual declared sign, not an inferred one from base × rate.
    raw_declared_by_row: dict[tuple[str, str], Decimal | None] = {}
    label_by_row: dict[tuple[str, str], str | None] = {}
    # A row is "complete" only when every one of its contributing detail
    # rows produced a chosen amount. Start optimistic, flip to False on the
    # first non-calculable variant seen.
    complete_by_row: dict[tuple[str, str], bool] = {}
    # Qualifier set per row — derived from detail's own assiette_qualifier,
    # NOT the global qualifiers_by_ctp. This is the component-scoping fix:
    # 100D's individual side must only pull 920-scoped S81 sums, not the
    # union of 920+921.
    qualifiers_by_row: dict[tuple[str, str], set[str]] = {}

    for d in details:
        ctp = d.ctp_code or ""
        if not ctp:
            continue
        mapped = d.mapped_code or ctp
        row_key = (ctp, mapped)
        if row_key not in declared_by_row:
            ordered_keys.append(row_key)
            declared_by_row[row_key] = None
            raw_declared_by_row[row_key] = None
            label_by_row[row_key] = d.label
            complete_by_row[row_key] = True
            qualifiers_by_row[row_key] = set()

        if d.assiette_qualifier:
            qualifiers_by_row[row_key].add(d.assiette_qualifier)

        # Chosen amount per detail mirrors _compute_urssaf's ctp_amount logic.
        chosen: Decimal | None
        if d.declared_amount is not None:
            chosen = d.declared_amount
        elif d.computed_amount is not None:
            chosen = d.computed_amount
        else:
            chosen = None

        if chosen is None:
            # Any non-calculable variant downgrades the whole row.
            complete_by_row[row_key] = False
        else:
            current = declared_by_row[row_key]
            declared_by_row[row_key] = (current or Decimal(0)) + chosen

        # Track raw declared separately (only S21.G00.23.005 values).
        if d.declared_amount is not None:
            cur_raw = raw_declared_by_row[row_key]
            raw_declared_by_row[row_key] = (cur_raw or Decimal(0)) + d.declared_amount

    breakdowns: list[UrssafCodeBreakdown] = []
    for row_key in ordered_keys:
        ctp, mapped = row_key
        is_complete = complete_by_row.get(row_key, False)
        # When the collapse is incomplete, suppress the per-row declared
        # total so the UI cannot read a misleading "full" amount. The
        # individual side (from S78/S81) is orthogonal and stays real.
        declared = declared_by_row[row_key] if is_complete else None
        label = label_by_row[row_key]
        row_warnings: list[str] = []
        if not is_complete:
            row_warnings.append(_PARTIAL_CTP_WARNING)

        # Phase 2: Rule lookup and activation check.
        rule = get_rule(ctp)
        # display_absolute is the explicit reduction-family flag. It must be
        # attached to every row emitted for this CTP — including non_rattache
        # exits below — so reduction rows always render as absolute magnitudes
        # in the UI, regardless of which phase refused them.
        display_absolute = bool(rule is not None and rule.display_absolute)

        def _emit_non_rattache(
            reason: str,
            *,
            individual_code: str | None = None,
            applied_codes: list[str] | None = None,
            excluded: list[dict[str, str]] | None = None,
        ) -> None:
            breakdowns.append(UrssafCodeBreakdown(
                ctp_code=ctp,
                ctp_label=label,
                mapped_code=mapped,
                individual_code=individual_code,
                mapping_status="non_rattache",
                mapping_reason=reason,
                applied_individual_codes=applied_codes or [],
                excluded_individual_codes=excluded or [],
                declared_amount=declared,
                display_absolute=display_absolute,
                warnings=row_warnings,
            ))

        if rule is None:
            _emit_non_rattache("no_verified_mapping_rule")
            continue

        if not is_rule_active(rule):
            _emit_non_rattache("rule_not_enabled")
            continue

        # Phase 3: Top-level condition check (for guarded rules).
        if rule.conditions.requires_insee_commune:
            if not insee_codes_by_ctp.get(ctp):
                _emit_non_rattache("missing_runtime_condition")
                continue
        if rule.conditions.threshold_rule is not None:
            _emit_non_rattache("missing_runtime_condition")
            continue

        # Phase 3b: Sign condition check — uses only the raw declared amount
        # from S21.G00.23.005, never a recomputed fallback. For reduction
        # rules flagged as display_absolute, the sign check is relaxed to an
        # abs-value sanity check: any non-zero raw_declared passes, because
        # these CTPs are compared and displayed on absolute magnitudes by
        # product decision (the raw sign is not a business constraint).
        if rule.conditions.sign_condition is not None:
            raw_declared = raw_declared_by_row.get(row_key)
            if raw_declared is None or raw_declared == 0:
                _emit_non_rattache("missing_sign_context")
                continue
            if not rule.display_absolute:
                sign_ok = (
                    (rule.conditions.sign_condition == "negative" and raw_declared < 0)
                    or (rule.conditions.sign_condition == "positive" and raw_declared > 0)
                )
                if not sign_ok:
                    _emit_non_rattache("sign_condition_not_met")
                    continue

        # Phase 4: S81 row scanning.
        included_rows: list[tuple[int, str, Decimal, list[int], str, str]] = []
        applied_codes: set[str] = set()
        excluded_entries: list[dict[str, str]] = []

        if rule.components is not None:
            # Path A: Component-scoped matching. Qualifiers come from this
            # row's own qualifier set — NOT the global qualifiers_by_ctp.
            declared_qualifiers = qualifiers_by_row.get(row_key, set())

            # 4a-pre: Refuse if any S23 line for this CTP had an empty
            # qualifier. The collapsed declared amount includes the
            # empty-qualifier line, so evaluating against only the known
            # qualifiers would compare a partial employee side against a
            # full declared total — violating the "no partial guess" rule.
            if ctps_with_empty_qualifier and ctp in ctps_with_empty_qualifier:
                _emit_non_rattache("missing_declared_qualifier")
                continue

            # 4a: Check for unsupported declared qualifiers.
            supported_qualifiers: set[str] = set()
            for comp in rule.components:
                supported_qualifiers |= comp.assiette_qualifiers_s23
            unsupported = declared_qualifiers - supported_qualifiers
            if unsupported:
                _emit_non_rattache("unsupported_declared_qualifier")
                continue

            # 4b: Determine active components — scoped to this row's qualifier.
            active_components = [
                comp for comp in rule.components
                if declared_qualifiers & comp.assiette_qualifiers_s23
            ]
            if not active_components:
                _emit_non_rattache("missing_declared_qualifier")
                continue

            # 4c: Build combined acceptance set from active components.
            acceptance_set: set[tuple[str, str]] = set()
            for comp in active_components:
                for code in comp.individual_codes_s81:
                    for base in comp.base_codes_s78:
                        acceptance_set.add((code, base))

            # 4d: Scan S81 rows — row-level matching.
            candidate_codes = {
                code for comp in active_components
                for code in comp.individual_codes_s81
            }
            for s81_code in candidate_codes:
                for row in s81_by_code.get(s81_code, []):
                    emp_idx, emp_name, amt, lines, base_code_78 = row
                    if (s81_code, base_code_78) in acceptance_set:
                        included_rows.append(
                            (emp_idx, emp_name, amt, lines, base_code_78, s81_code)
                        )
                        applied_codes.add(s81_code)
                    else:
                        excluded_entries.append(
                            {"code": s81_code, "reason": "wrong_base"}
                        )
        else:
            # Path B: Flat matching (simple 1:1 or 1:N rules without components).
            for s81_code in rule.individual_codes_s81:
                for row in s81_by_code.get(s81_code, []):
                    emp_idx, emp_name, amt, lines, base_code_78 = row
                    if rule.base_codes_s78 and base_code_78 not in rule.base_codes_s78:
                        excluded_entries.append(
                            {"code": s81_code, "reason": "wrong_base"}
                        )
                        continue
                    included_rows.append(
                        (emp_idx, emp_name, amt, lines, base_code_78, s81_code)
                    )
                    applied_codes.add(s81_code)

        # Phase 4.5: Employee contract nature filtering.
        status_filter_missing_context = False
        if contract_natures_by_emp is not None and (
            rule.conditions.requires_contract_nature
            or rule.conditions.excludes_contract_nature
        ):
            filtered_rows: list[tuple[int, str, Decimal, list[int], str, str]] = []
            for row in included_rows:
                emp_natures = contract_natures_by_emp.get(row[0], frozenset())
                if rule.conditions.requires_contract_nature:
                    if not emp_natures:
                        # Employee has no S21.G00.40.007 — cannot evaluate
                        status_filter_missing_context = True
                        continue
                    if not (emp_natures & rule.conditions.requires_contract_nature):
                        continue
                if rule.conditions.excludes_contract_nature:
                    if not emp_natures:
                        # Employee has no S21.G00.40.007 — cannot evaluate
                        status_filter_missing_context = True
                        continue
                    if emp_natures & rule.conditions.excludes_contract_nature:
                        continue
                filtered_rows.append(row)
            included_rows = filtered_rows

        # Phase 5: Aggregate and emit.
        individual_code_display = (
            rule.individual_codes_s81[0]
            if len(rule.individual_codes_s81) == 1 and rule.components is None
            else None
        )

        # If any candidate rows were dropped because the employee had no
        # S21.G00.40.007, the remaining rows (if any) represent only part
        # of the eligible population. Presenting that partial sum as a
        # trustworthy "rattachable" total would violate the safety model.
        if status_filter_missing_context:
            _emit_non_rattache(
                "missing_employee_status_context",
                individual_code=individual_code_display,
                applied_codes=sorted(applied_codes),
                excluded=excluded_entries,
            )
            continue

        if not included_rows:
            breakdowns.append(UrssafCodeBreakdown(
                ctp_code=ctp,
                ctp_label=label,
                mapped_code=mapped,
                individual_code=individual_code_display,
                mapping_status="manquant_individuel",
                mapping_reason="matched_rule",
                applied_individual_codes=sorted(applied_codes),
                excluded_individual_codes=excluded_entries,
                declared_amount=declared,
                display_absolute=display_absolute,
                warnings=row_warnings,
            ))
            continue

        # Aggregate by employee_index — one row per employee, with the
        # contributing S81 codes surfaced as metadata.
        by_emp: dict[int, tuple[str, Decimal, list[int], set[str]]] = {}
        for emp_idx, emp_name, amt, lines, _base, s81_code in included_rows:
            if emp_idx in by_emp:
                prev_name, prev_amt, prev_lines, prev_codes = by_emp[emp_idx]
                by_emp[emp_idx] = (
                    prev_name,
                    prev_amt + amt,
                    prev_lines + list(lines),
                    prev_codes | {s81_code},
                )
            else:
                by_emp[emp_idx] = (emp_name, amt, list(lines), {s81_code})

        individual_total = sum(
            (amt for _, amt, _, _ in by_emp.values()),
            Decimal(0),
        )
        employees = [
            EmployeeContributionBreakdown(
                employee_name=name,
                individual_code=sorted(codes)[0] if codes else None,
                individual_codes=sorted(codes),
                amount=amt,
                record_lines=rec_lines,
            )
            for idx, (name, amt, rec_lines, codes) in sorted(
                by_emp.items(),
                key=lambda item: (item[1][0], item[0]),
            )
        ]

        delta: Decimal | None = None
        if declared is not None:
            delta = declared - individual_total
        if display_absolute:
            # Business tolerance for reduction rows compares magnitudes.
            delta_within_unit = _urssaf_row_delta_within_unit(
                abs(declared) if declared is not None else None,
                abs(individual_total),
            )
        else:
            delta_within_unit = _urssaf_row_delta_within_unit(declared, individual_total)

        breakdowns.append(UrssafCodeBreakdown(
            ctp_code=ctp,
            ctp_label=label,
            mapped_code=mapped,
            individual_code=individual_code_display,
            mapping_status="rattachable",
            mapping_reason="matched_rule",
            applied_individual_codes=sorted(applied_codes),
            excluded_individual_codes=excluded_entries,
            declared_amount=declared,
            individual_amount=individual_total,
            delta=delta,
            delta_within_unit=delta_within_unit,
            display_absolute=display_absolute,
            employees=employees,
            warnings=row_warnings,
        ))

    return breakdowns


def _compute_urssaf(
    organism_id: str,
    s20_blocks: list[BlockGroup],
    s22_blocks: list[BlockGroup],
    est_groups: EstablishmentBlockGroups,
    employee_blocks: list[EmployeeBlock],
    reference_date: dt.date | None,
) -> ContributionComparisonItem:
    label, _, _ = lookup_organism(organism_id)
    warnings: list[str] = []
    has_regularization = False

    # Aggregate amount — sum across all S20 blocks for this organism
    agg_total = Decimal(0)
    has_agg = False
    for s20 in s20_blocks:
        amt = _dec(_find_value(s20.records, "S21.G00.20.005"))
        if amt is not None:
            agg_total += amt
            has_agg = True
        if _check_regularization(s20):
            has_regularization = True
    aggregate_amount = agg_total if has_agg else None

    # Find ALL matching S22 bordereaux for this organism
    matching_s22_blocks: list[BlockGroup] = []
    for s22 in s22_blocks:
        s22_org = _find_value(s22.records, "S21.G00.22.001")
        if s22_org and s22_org.strip() == organism_id:
            matching_s22_blocks.append(s22)

    if len(matching_s22_blocks) > 1:
        warnings.append("multiple_s22_bordereaux")

    bordereau_amount: Decimal | None = None
    bord_total = Decimal(0)
    has_bord = False
    all_s23_children: list[BlockGroup] = []
    for s22 in matching_s22_blocks:
        amt = _dec(_find_value(s22.records, "S21.G00.22.005"))
        if amt is not None:
            bord_total += amt
            has_bord = True
        if _check_regularization(s22):
            has_regularization = True
        all_s23_children.extend(s22.children)
    bordereau_amount = bord_total if has_bord else None

    # CTP detail from S23 children of ALL matching S22 blocks
    details: list[ContributionComparisonDetail] = []
    component_total = Decimal(0)
    n_recalculated_ctps = 0
    has_ctp = False
    non_calculable_ctp_count = 0
    qualifiers_by_ctp: dict[str, set[str]] = {}
    insee_codes_by_ctp: dict[str, set[str]] = {}
    ctps_with_empty_qualifier: set[str] = set()

    if matching_s22_blocks:
        for s23 in all_s23_children:
            ctp_code = _find_value(s23.records, "S21.G00.23.001") or ""
            assiette_qual = _find_value(s23.records, "S21.G00.23.002") or ""
            insee_code = _find_value(s23.records, "S21.G00.23.006") or ""
            if ctp_code and assiette_qual:
                qualifiers_by_ctp.setdefault(ctp_code, set()).add(assiette_qual)
            if ctp_code and not assiette_qual:
                ctps_with_empty_qualifier.add(ctp_code)
            if ctp_code and insee_code:
                insee_codes_by_ctp.setdefault(ctp_code, set()).add(insee_code)
            key = f"{ctp_code}/{assiette_qual}/{insee_code}".rstrip("/")
            mapped_code, reference_label, short_label, reference_fmt, expected_rate = _select_reference_rate(
                ctp_code,
                assiette_qual or None,
                reference_date,
            )

            declared_raw = _find_value(s23.records, "S21.G00.23.005")
            rate_raw = _find_value(s23.records, "S21.G00.23.003")
            base_raw = _find_value(s23.records, "S21.G00.23.004")

            declared = _dec(declared_raw) if declared_raw and declared_raw.strip() else None
            rate = _dec(rate_raw) if rate_raw and rate_raw.strip() else None
            base = _dec(base_raw) if base_raw and base_raw.strip() else None
            is_at_rate_only = (
                _is_at_rate_only_ctp(ctp_code, assiette_qual or None)
                and expected_rate is not None
                and declared is None
                and rate is not None
                and rate < expected_rate
            )

            recomputed: Decimal | None = None
            effective_rate = None
            if not is_at_rate_only:
                effective_rate = expected_rate if expected_rate is not None else rate
            # Net-entreprises documents F/R CTP formats as special
            # reduction/regularization lines whose business amount lives in
            # S21.G00.23.005 rather than being safely recomputable from
            # S21.G00.23.004 × taux.
            can_recompute_amount = not is_at_rate_only and reference_fmt not in {"F", "R"}
            if base is not None and effective_rate is not None and can_recompute_amount:
                recomputed = (base * effective_rate / Decimal(100)).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                n_recalculated_ctps += 1

            # Amount to use for this CTP
            if declared is not None:
                ctp_amount = declared
            elif recomputed is not None:
                ctp_amount = recomputed
            else:
                ctp_amount = None

            # Detail status — classification driven by tolerance rules
            ctp_status = "ok"
            ctp_delta: Decimal | None = None
            ctp_warnings: list[str] = []
            rate_mismatch = False
            amount_mismatch = False

            if rate is not None and expected_rate is not None and not is_at_rate_only:
                rate_mismatch = not _within_tolerance(rate, expected_rate, _RATE_TOL_0001)
                if rate_mismatch:
                    ctp_warnings.append(
                        f"CTP {mapped_code}: taux DSN {rate} ≠ taux référence {expected_rate}"
                    )

            if declared is not None and recomputed is not None:
                ctp_delta = declared - recomputed
                amount_mismatch = not _within_tolerance(declared, recomputed, _TOL_001)
                if amount_mismatch or rate_mismatch:
                    ctp_status = "ecart"
                if amount_mismatch:
                    ctp_warnings.append(
                        f"CTP {mapped_code}: déclaré {declared} ≠ recalculé {recomputed}"
                    )
            elif declared is not None:
                ctp_status = "ecart" if rate_mismatch else "declared_only"
            elif recomputed is not None:
                ctp_status = "computed_only"
            else:
                ctp_status = "non_calculable"
                non_calculable_ctp_count += 1

            if ctp_amount is not None:
                component_total += ctp_amount
                has_ctp = True

            details.append(ContributionComparisonDetail(
                key=key,
                label=reference_label or lookup_ctp(ctp_code) or ctp_code,
                short_label=short_label,
                ctp_code=ctp_code or None,
                mapped_code=mapped_code or None,
                assiette_qualifier=assiette_qual or None,
                assiette_label=_format_assiette_label(assiette_qual),
                rate=rate,
                expected_rate=expected_rate,
                base_amount=base,
                declared_amount=declared,
                computed_amount=recomputed,
                delta=ctp_delta,
                status=ctp_status,
                rate_mismatch=rate_mismatch,
                amount_mismatch=amount_mismatch,
                record_lines=_record_lines(s23.records),
                warnings=ctp_warnings,
            ))

    component_amount = component_total if has_ctp else None
    component_comparison_complete = has_ctp and non_calculable_ctp_count == 0
    if has_ctp and non_calculable_ctp_count > 0:
        warnings.append(
            "Sous-total CTP non affiché : "
            f"{non_calculable_ctp_count} ligne(s) ne peuvent pas être "
            "rapprochées de façon fiable à partir de la DSN seule."
        )
        # Keep line-level details, but do not present a partial subtotal as the
        # full detailed amount in the top-level card.
        component_amount = None

    # Deltas
    agg_vs_bord_delta: Decimal | None = None
    bord_vs_comp_delta: Decimal | None = None

    if aggregate_amount is not None and bordereau_amount is not None:
        agg_vs_bord_delta = aggregate_amount - bordereau_amount

    if bordereau_amount is not None and component_amount is not None:
        bord_vs_comp_delta = bordereau_amount - component_amount

    # Status determination
    if aggregate_amount is None:
        status = "manquant_agrege"
    elif not matching_s22_blocks:
        status = "manquant_bordereau"
    elif not has_ctp:
        status = "manquant_detail"
    else:
        # Control 1: versement vs bordereau
        ctrl1_ok = bordereau_amount is not None and _rounded_to_unit_ok(
            aggregate_amount, bordereau_amount
        )
        if not component_comparison_complete:
            status = "ok" if ctrl1_ok else "ecart"
        else:
            # Control 2: bordereau vs sum(CTP) — arrondi à l'entier
            ctrl2_ok = (
                bordereau_amount is not None
                and component_amount is not None
                and _rounded_to_unit_ok(bordereau_amount, component_amount)
            )
            if ctrl1_ok and ctrl2_ok:
                status = "ok"
            else:
                status = "ecart"

    if has_regularization:
        warnings.append(REGULARIZATION_WARNING)

    # Slice C: per-CTP drill-down to employee-level amounts via Slice B mapping.
    s81_by_code, has_any_s78_s81 = _collect_s81_by_individual_code(employee_blocks)
    contract_natures_by_emp = _collect_employee_contract_natures(employee_blocks)
    urssaf_code_breakdowns = _build_urssaf_code_breakdowns(
        details, s81_by_code, qualifiers_by_ctp, insee_codes_by_ctp,
        ctps_with_empty_qualifier, contract_natures_by_emp,
    )

    # Warn when individual data is present in the file but some CTPs cannot
    # be drilled down. The warning text reflects the actual reason so users
    # know what is missing (no rule, rule blocked, incomplete declared side).
    if has_any_s78_s81:
        _reason_labels = {
            "no_verified_mapping_rule": "sans mapping fiable",
            "rule_not_enabled": "règle en attente de validation experte",
            "missing_runtime_condition": "conditions de rattachement non réunies",
            "missing_declared_qualifier": "qualifiant d'assiette manquant côté déclaratif",
            "unsupported_declared_qualifier": "variante d'assiette non prise en charge",
            "missing_sign_context": "contexte de signe manquant pour le montant déclaré",
            "sign_condition_not_met": "condition de signe non respectée",
            "missing_employee_status_context": "statut salarié (S21.G00.40.007) manquant",
        }
        for reason, reason_label in _reason_labels.items():
            ctps = sorted(
                b.ctp_code for b in urssaf_code_breakdowns
                if b.mapping_status == "non_rattache" and b.mapping_reason == reason
            )
            if ctps:
                warnings.append(
                    f"Données individuelles (S78/S81) présentes — "
                    f"{reason_label} pour : {', '.join(ctps)}."
                )

    return ContributionComparisonItem(
        family="urssaf",
        organism_id=organism_id,
        organism_label=label,
        aggregate_amount=aggregate_amount,
        bordereau_amount=bordereau_amount,
        component_amount=component_amount,
        aggregate_vs_bordereau_delta=agg_vs_bord_delta,
        bordereau_vs_component_delta=bord_vs_comp_delta,
        status=status,
        details=details,
        warnings=warnings,
        urssaf_code_breakdowns=urssaf_code_breakdowns,
    )


# ---------------------------------------------------------------------------
# Prévoyance / Mutuelle reconciliation
# ---------------------------------------------------------------------------


@dataclass
class S15Entry:
    """One parsed S21.G00.15 adhesion block."""

    contract_ref: str
    organism_id: str
    adhesion_id: str


def _build_s15_entries(
    s15_blocks: list[BlockGroup],
) -> tuple[list[S15Entry], list[str]]:
    """Extract all S15 entries preserving the full business key.

    Returns (entries, warnings).  Same contract_ref pointing to different
    organisms is ambiguous.  Same contract_ref + same organism + different
    adhesion_id produces distinct entries (not ambiguous — two adhesions).
    """
    entries: list[S15Entry] = []
    warnings: list[str] = []
    # Track contract_ref → set of organism_ids to detect cross-organism ambiguity
    orgs_by_cref: dict[str, set[str]] = {}
    # Deduplicate by full key so repeated identical S15 blocks don't double-count
    seen_keys: set[tuple[str, str, str]] = set()

    for s15 in s15_blocks:
        contract_ref = (_find_value(s15.records, "S21.G00.15.001") or "").strip()
        organism_id = (_find_value(s15.records, "S21.G00.15.002") or "").strip()
        adhesion_id = (_find_value(s15.records, "S21.G00.15.005") or "").strip()

        if not contract_ref:
            continue

        orgs_by_cref.setdefault(contract_ref, set()).add(organism_id)

        key = (contract_ref, organism_id, adhesion_id)
        if key not in seen_keys:
            seen_keys.add(key)
            entries.append(S15Entry(
                contract_ref=contract_ref,
                organism_id=organism_id,
                adhesion_id=adhesion_id,
            ))

    for cref, org_ids in orgs_by_cref.items():
        if len(org_ids) > 1:
            warnings.append(f"ambiguous_s15_mapping: contract_ref '{cref}'")

    return entries, warnings


def _build_s70_map(
    employee_blocks: list[EmployeeBlock],
) -> tuple[dict[str, str], list[str]]:
    """Build affiliation_id → adhesion_id map from S70 blocks across employees.

    Returns (map, warnings).
    """
    result: dict[str, str] = {}
    ambiguous: set[str] = set()
    warnings: list[str] = []

    for emp in employee_blocks:
        emp_groups = group_employee_blocks(emp)
        for s70 in emp_groups.s70_blocks:
            affil_id = (_find_value(s70.records, "S21.G00.70.012") or "").strip()
            adhes_id = (_find_value(s70.records, "S21.G00.70.013") or "").strip()
            if not affil_id:
                continue
            if affil_id in result and result[affil_id] != adhes_id:
                ambiguous.add(affil_id)
            else:
                result[affil_id] = adhes_id

    for affil in ambiguous:
        warnings.append(f"ambiguous_s70_mapping: affiliation_id '{affil}'")

    return result, warnings


def _compute_complementary(
    organism_id: str,
    s20_blocks: list[BlockGroup],
    est_groups: EstablishmentBlockGroups,
    employee_blocks: list[EmployeeBlock],
    s15_entries: list[S15Entry],
    s15_warnings: list[str],
    s70_map: dict[str, str],
    s70_warnings: list[str],
) -> list[ContributionComparisonItem]:
    """Compute reconciliation for a complementary organism.

    Accepts all S20 blocks for this organism. Merges aggregate amounts and S55
    children across blocks, then emits one item per unique
    (organism_id, contract_ref, adhesion_id) key from S15.
    """
    label, _, registry_family = lookup_organism(organism_id)
    has_regularization = False

    # Bridge-link validation
    s15_present = len(est_groups.s15_blocks) > 0
    s70_present = len(s70_map) > 0
    s15_ambiguous = len(s15_warnings) > 0
    s70_ambiguous = len(s70_warnings) > 0

    base_warnings: list[str] = []
    if not s15_present:
        base_warnings.append("missing_structuring_block_s15")
    if not s70_present:
        base_warnings.append("missing_structuring_block_s70")
    base_warnings.extend(s15_warnings)
    base_warnings.extend(s70_warnings)

    s70_valid = s70_present and not s70_ambiguous
    bridge_valid = s15_present and not s15_ambiguous and s70_valid

    # Aggregate amount — sum across ALL S20 blocks for this organism
    agg_total = Decimal(0)
    has_agg = False
    for s20 in s20_blocks:
        amt = _dec(_find_value(s20.records, "S21.G00.20.005"))
        if amt is not None:
            agg_total += amt
            has_agg = True
        if _check_regularization(s20):
            has_regularization = True
    aggregate_amount = agg_total if has_agg else None

    # Collect S55 children across ALL S20 blocks, indexed by contract_ref
    s55_by_contract: dict[str, list[BlockGroup]] = {}
    for s20 in s20_blocks:
        for s55 in s20.children:
            cref = (_find_value(s55.records, "S21.G00.55.003") or "").strip()
            s55_by_contract.setdefault(cref, []).append(s55)
            if _check_regularization(s55):
                has_regularization = True

    # Collect contracts for this organism from S15 entries — full business key
    # Each unique (contract_ref, adhesion_id) for this organism gets its own item.
    org_contracts: list[tuple[str, str]] = []
    for entry in s15_entries:
        if entry.organism_id == organism_id:
            pair = (entry.contract_ref, entry.adhesion_id)
            if pair not in org_contracts:
                org_contracts.append(pair)

    # If no S15 contracts found, produce a single non-split item
    if not org_contracts:
        fallback_family = registry_family if registry_family in ("prevoyance", "mutuelle") else "unclassified"
        warnings = list(base_warnings)
        comp_total = Decimal(0)
        has_comp = False
        for s55_list in s55_by_contract.values():
            for s55 in s55_list:
                amt = _dec(_find_value(s55.records, "S21.G00.55.001"))
                if amt is not None:
                    comp_total += amt
                    has_comp = True
        component_amount = comp_total if has_comp else None

        if has_regularization:
            warnings.append(REGULARIZATION_WARNING)

        return [ContributionComparisonItem(
            family=fallback_family,
            organism_id=organism_id,
            organism_label=label,
            aggregate_amount=aggregate_amount,
            component_amount=component_amount,
            status="non_rattache",
            warnings=warnings,
        )]

    # Detect contract_refs shared by multiple adhesions — S55 has no adhesion
    # discriminator so component amounts cannot be split across adhesions.
    adhesions_per_cref: dict[str, list[str]] = {}
    for cref, adhes in org_contracts:
        adhesions_per_cref.setdefault(cref, []).append(adhes)
    shared_crefs: set[str] = {
        cref for cref, adhes_list in adhesions_per_cref.items()
        if len(adhes_list) > 1
    }

    # Precompute component totals per contract_ref (once, not per adhesion)
    comp_by_cref: dict[str, Decimal | None] = {}
    for cref in {c for c, _ in org_contracts}:
        total = Decimal(0)
        found = False
        for s55 in s55_by_contract.get(cref, []):
            amt = _dec(_find_value(s55.records, "S21.G00.55.001"))
            if amt is not None:
                total += amt
                found = True
        # Include S55 with empty contract_ref if only one contract_ref
        if len(adhesions_per_cref) == 1:
            for s55 in s55_by_contract.get("", []):
                amt = _dec(_find_value(s55.records, "S21.G00.55.001"))
                if amt is not None:
                    total += amt
                    found = True
        comp_by_cref[cref] = total if found else None

    # One item per unique (contract_ref, adhesion_id)
    items: list[ContributionComparisonItem] = []
    for contract_ref, adhesion_id in org_contracts:
        item_family = lookup_complementary_family_override(organism_id, contract_ref)
        if item_family is None:
            item_family = registry_family if registry_family in ("prevoyance", "mutuelle") else "unclassified"
        warnings = list(base_warnings)
        cref_shared = contract_ref in shared_crefs

        # Component amount: only assignable when adhesion is sole owner of the cref.
        # When multiple adhesions share a cref, the S55 amount cannot be split —
        # set to None and downgrade instead of duplicating.
        if cref_shared:
            component_amount: Decimal | None = None
            warnings.append(
                f"component_not_allocable_across_adhesions: contract_ref "
                f"'{contract_ref}' shared by adhesions "
                f"{', '.join(adhesions_per_cref[contract_ref])}"
            )
        else:
            component_amount = comp_by_cref.get(contract_ref)

        # Individual amount from S78(31)/S81 linked through S70→adhesion_id
        ind_total = Decimal(0)
        has_ind = False
        details: list[ContributionComparisonDetail] = []

        if bridge_valid and adhesion_id:
            for emp in employee_blocks:
                emp_groups = group_employee_blocks(emp)
                emp_name = _employee_display_name(emp)

                for s78 in emp_groups.s78_blocks:
                    base_code = (_find_value(s78.records, "S21.G00.78.001") or "").strip()
                    if base_code != "31":
                        continue
                    affil_id = (_find_value(s78.records, "S21.G00.78.005") or "").strip()
                    linked_adhesion = s70_map.get(affil_id, "")
                    if linked_adhesion != adhesion_id:
                        continue

                    for s81 in s78.children:
                        amt = _dec(_find_value(s81.records, "S21.G00.81.004"))
                        if amt is not None:
                            ind_total += amt
                            has_ind = True
                            details.append(ContributionComparisonDetail(
                                key=emp_name,
                                label=f"S81 base 31 contrat {contract_ref}",
                                declared_amount=amt,
                                status="ok",
                                record_lines=_record_lines(s81.records),
                            ))

        individual_amount = ind_total if has_ind else None

        # Deltas and status
        agg_vs_comp = None
        agg_vs_ind = None

        if cref_shared:
            # Component not allocable per adhesion → non_calculable.
            # Raw individual still visible.
            status = "non_calculable"
        elif not bridge_valid:
            status = "non_rattache"
        elif component_amount is None and individual_amount is None:
            status = "manquant_detail"
        else:
            if component_amount is not None and individual_amount is not None:
                agg_vs_ind = component_amount - individual_amount
            if len(org_contracts) == 1:
                if aggregate_amount is not None and component_amount is not None:
                    agg_vs_comp = aggregate_amount - component_amount
                if aggregate_amount is not None and individual_amount is not None:
                    agg_vs_ind = aggregate_amount - individual_amount

            all_ok = True
            if len(org_contracts) == 1:
                if component_amount is not None and aggregate_amount is not None:
                    if not _within_tolerance(aggregate_amount, component_amount, _TOL_001):
                        all_ok = False
                if individual_amount is not None and aggregate_amount is not None:
                    if not _within_tolerance(aggregate_amount, individual_amount, _TOL_001):
                        all_ok = False
            else:
                if component_amount is not None and individual_amount is not None:
                    if not _within_tolerance(component_amount, individual_amount, _TOL_001):
                        all_ok = False
                elif component_amount is None and individual_amount is None:
                    all_ok = False
            status = "ok" if all_ok else "ecart"

        if has_regularization:
            warnings.append(REGULARIZATION_WARNING)

        items.append(ContributionComparisonItem(
            family=item_family,
            organism_id=organism_id,
            organism_label=label,
            aggregate_amount=aggregate_amount if len(org_contracts) == 1 else None,
            component_amount=component_amount,
            individual_amount=individual_amount,
            aggregate_vs_component_delta=agg_vs_comp,
            aggregate_vs_individual_delta=agg_vs_ind,
            status=status,
            details=details,
            warnings=warnings,
            adhesion_id=adhesion_id or None,
            contract_ref=contract_ref or None,
        ))

    return items


# ---------------------------------------------------------------------------
# Retraite reconciliation
# ---------------------------------------------------------------------------


def _compute_retraite(
    retraite_s20_blocks: list[tuple[str, BlockGroup]],
    employee_blocks: list[EmployeeBlock],
) -> list[ContributionComparisonItem]:
    """Compute retraite reconciliation for one or more retraite organisms."""
    if not retraite_s20_blocks:
        return []

    items: list[ContributionComparisonItem] = []

    # Compute individual total from S78{02,03}/S81{131,132,106,109}
    individual_total = Decimal(0)
    has_individual = False
    ind_details: list[ContributionComparisonDetail] = []

    for emp in employee_blocks:
        emp_groups = group_employee_blocks(emp)
        emp_name = _employee_display_name(emp)

        for s78 in emp_groups.s78_blocks:
            base_code = (_find_value(s78.records, "S21.G00.78.001") or "").strip()
            if base_code not in ("02", "03"):
                continue

            for s81 in s78.children:
                code_81 = (_find_value(s81.records, "S21.G00.81.001") or "").strip()
                if code_81 not in ("131", "132", "106", "109"):
                    continue

                amt = _dec(_find_value(s81.records, "S21.G00.81.004"))
                if amt is not None:
                    individual_total += amt
                    has_individual = True
                    ind_details.append(ContributionComparisonDetail(
                        key=f"{emp_name}/{code_81}",
                        label=f"S81 code {code_81} base {base_code}",
                        declared_amount=amt,
                        status="ok",
                        record_lines=_record_lines(s81.records),
                    ))

    individual_amount = individual_total if has_individual else None

    multi_caisse = len(retraite_s20_blocks) > 1

    for organism_id, s20 in retraite_s20_blocks:
        label, _, _ = lookup_organism(organism_id)
        warnings: list[str] = []
        has_regularization = _check_regularization(s20)

        aggregate_amount = _dec(_find_value(s20.records, "S21.G00.20.005"))

        if multi_caisse:
            warnings.append("multiple_retirement_organisms_unallocated")

        delta: Decimal | None = None
        if aggregate_amount is not None and individual_amount is not None:
            if not multi_caisse:
                delta = aggregate_amount - individual_amount

        # Status
        if aggregate_amount is None:
            status = "manquant_agrege"
        elif individual_amount is None:
            status = "manquant_individuel"
        elif multi_caisse:
            # Cannot compare per-caisse — no allocation key available.
            # Must not return ok/ecart since no comparison was performed.
            status = "non_calculable"
        elif _within_tolerance(aggregate_amount, individual_amount, _TOL_001):
            status = "ok"
        else:
            status = "ecart"

        if has_regularization:
            warnings.append(REGULARIZATION_WARNING)

        items.append(ContributionComparisonItem(
            family="retraite",
            organism_id=organism_id,
            organism_label=label,
            aggregate_amount=aggregate_amount,
            individual_amount=individual_amount if not multi_caisse else None,
            aggregate_vs_individual_delta=delta,
            status=status,
            details=ind_details if not multi_caisse else [],
            warnings=warnings,
        ))

    return items


# ---------------------------------------------------------------------------
# Unclassified outcome
# ---------------------------------------------------------------------------


def _make_unclassified(
    organism_id: str,
    s20_block: BlockGroup,
    warning_key: str,
) -> ContributionComparisonItem:
    label, _, _ = lookup_organism(organism_id)
    aggregate_amount = _dec(_find_value(s20_block.records, "S21.G00.20.005"))

    return ContributionComparisonItem(
        family="unclassified",
        organism_id=organism_id,
        organism_label=label,
        aggregate_amount=aggregate_amount,
        status="non_calculable",
        warnings=[warning_key],
    )


# ---------------------------------------------------------------------------
# Count computation
# ---------------------------------------------------------------------------


def _compute_counts(items: list[ContributionComparisonItem]) -> tuple[int, int, int]:
    """Compute (ok_count, mismatch_count, warning_count).

    warning_count is the number of **unique warning strings** across all items
    and their details.  This is a product contract: the same warning text
    appearing on multiple items is counted once.  Duplicates are deduplicated
    by exact string equality.
    """
    ok = sum(1 for i in items if i.status == "ok")
    ecart = sum(1 for i in items if i.status == "ecart")
    seen: set[str] = set()
    for item in items:
        for w in item.warnings:
            seen.add(w)
        for detail in item.details:
            for w in detail.warnings:
                seen.add(w)
    return ok, ecart, len(seen)


# ---------------------------------------------------------------------------
# Public orchestrator
# ---------------------------------------------------------------------------


def compute_contribution_comparisons(
    est_block: EstablishmentBlock,
    reference_date: dt.date | None = None,
) -> ContributionComparisons:
    """Compute all contribution comparisons for one establishment."""
    est_groups = group_establishment_blocks(est_block)
    structural_warnings: list[str] = list(est_groups.warnings)

    # Collect employee-level grouping warnings
    for emp in est_block.employee_blocks:
        emp_grp = group_employee_blocks(emp)
        structural_warnings.extend(emp_grp.warnings)

    # Collect organism IDs from structural linkage blocks
    s22_organism_ids: set[str] = set()
    for s22 in est_groups.s22_blocks:
        org_id = (_find_value(s22.records, "S21.G00.22.001") or "").strip()
        if org_id:
            s22_organism_ids.add(org_id)

    s15_organism_ids: set[str] = set()
    for s15 in est_groups.s15_blocks:
        org_id = (_find_value(s15.records, "S21.G00.15.002") or "").strip()
        if org_id:
            s15_organism_ids.add(org_id)

    # Build S15 entries and S70 map (shared across all prevoyance/mutuelle)
    s15_entries, s15_warnings = _build_s15_entries(est_groups.s15_blocks)
    s70_map, s70_warnings = _build_s70_map(est_block.employee_blocks)

    # Classify each S20 block
    items: list[ContributionComparisonItem] = []
    dgfip_s20_blocks: list[BlockGroup] = []
    urssaf_s20_by_org: dict[str, list[BlockGroup]] = {}
    complementary_s20_by_org: dict[str, list[BlockGroup]] = {}
    retraite_s20: list[tuple[str, BlockGroup]] = []

    for s20 in est_groups.s20_blocks:
        organism_id = (_find_value(s20.records, "S21.G00.20.001") or "").strip()
        if not organism_id:
            continue

        family = _classify_s20(organism_id, s22_organism_ids, s15_organism_ids)

        if family == "pas":
            dgfip_s20_blocks.append(s20)
        elif family == "urssaf":
            urssaf_s20_by_org.setdefault(organism_id, []).append(s20)
        elif family == "complementary":
            complementary_s20_by_org.setdefault(organism_id, []).append(s20)
        elif family == "retraite":
            retraite_s20.append((organism_id, s20))
        else:
            # Determine warning type
            if organism_id in s15_organism_ids:
                warning = (
                    f"s15_linked_unknown_subtype: organism {organism_id} is linked "
                    "via S15 but registry does not resolve to prevoyance or mutuelle"
                )
            else:
                warning = f"unclassified_organism: {organism_id}"
            items.append(_make_unclassified(organism_id, s20, warning))

    # PAS
    if dgfip_s20_blocks:
        items.append(_compute_pas(dgfip_s20_blocks, est_block.employee_blocks))

    # URSSAF
    for org_id, s20_list in urssaf_s20_by_org.items():
        items.append(
            _compute_urssaf(
                org_id,
                s20_list,
                est_groups.s22_blocks,
                est_groups,
                est_block.employee_blocks,
                reference_date,
            )
        )

    # Complementary (family resolved per contract)
    for org_id, s20_list in complementary_s20_by_org.items():
        items.extend(_compute_complementary(
            org_id, s20_list, est_groups, est_block.employee_blocks,
            s15_entries, s15_warnings, s70_map, s70_warnings,
        ))

    # Retraite
    items.extend(_compute_retraite(retraite_s20, est_block.employee_blocks))

    # Propagate structural orphan warnings so they always reach the payload.
    if structural_warnings:
        if items:
            # Distribute to each item so they surface in context
            for item in items:
                for w in structural_warnings:
                    if w not in item.warnings:
                        item.warnings.append(w)
        else:
            # No comparison items — create a carrier so warnings are not lost.
            # This is a technical visibility mechanism, not a real organism
            # record.  It exists solely to surface structural anomaly warnings
            # (orphan blocks, etc.) in the serialized payload and warning_count
            # when no S20 versement blocks produced comparison items.
            # Contract: family="unclassified", status="non_calculable",
            # organism_id=None, all amounts None.
            items.append(ContributionComparisonItem(
                family="unclassified",
                status="non_calculable",
                warnings=list(structural_warnings),
            ))

    # Counts
    ok_count, mismatch_count, warning_count = _compute_counts(items)

    return ContributionComparisons(
        items=items,
        ok_count=ok_count,
        mismatch_count=mismatch_count,
        warning_count=warning_count,
    )


def merge_contribution_comparisons(
    comparisons_list: list[ContributionComparisons],
) -> ContributionComparisons:
    """Merge contribution comparisons from multiple establishments."""
    all_items: list[ContributionComparisonItem] = []
    for cc in comparisons_list:
        all_items.extend(cc.items)

    ok_count, mismatch_count, warning_count = _compute_counts(all_items)

    return ContributionComparisons(
        items=all_items,
        ok_count=ok_count,
        mismatch_count=mismatch_count,
        warning_count=warning_count,
    )
