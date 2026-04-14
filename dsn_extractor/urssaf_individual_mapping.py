"""Backward-compatible shim for the URSSAF CTP → individual-code mapping.

The canonical source of truth is now ``dsn_extractor.urssaf_mapping_rules``.
This module delegates to that module while preserving the original public API
(``is_urssaf_code_mappable``, ``get_individual_code_for_ctp``,
``load_mapping``) so existing callers do not break.

The former TSV file ``data/urssaf_individual_mapping.tsv`` is no longer loaded.
"""

from __future__ import annotations

from dataclasses import dataclass

from dsn_extractor.urssaf_mapping_rules import (
    UrssafMappingRule,
    all_rules,
    get_rule,
    is_rule_active,
)


# ---------------------------------------------------------------------------
# Recognized URSSAF detail statuses
# ---------------------------------------------------------------------------

URSSAF_DETAIL_STATUSES: tuple[str, ...] = (
    "ok",
    "ecart",
    "non_calculable",
    "non_rattache",
    "declared_only",
    "computed_only",
)


# ---------------------------------------------------------------------------
# Legacy data class (kept for any external consumers)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class UrssafIndividualMapping:
    """One verified CTP → individual-code row (legacy format)."""

    ctp_code: str
    ctp_label: str
    individual_code_s81: str
    ops_rule: str
    source_ref: str


# ---------------------------------------------------------------------------
# Public API (backward-compatible delegates)
# ---------------------------------------------------------------------------

def load_mapping() -> dict[str, UrssafIndividualMapping]:
    """Return a dict of active 1:1 rules in the legacy format (ctp_code → row).

    Rules with multiple individual codes or components (1:N) are excluded —
    they cannot be faithfully represented as a single ``individual_code_s81``.
    """
    result: dict[str, UrssafIndividualMapping] = {}
    for ctp_code, rule in all_rules().items():
        if not is_rule_active(rule):
            continue
        if rule.components is not None:
            continue
        if len(rule.individual_codes_s81) != 1:
            continue
        result[ctp_code] = _rule_to_legacy(rule)
    return result


def is_urssaf_code_mappable(ctp_code: str | None) -> bool:
    """Return True if the CTP code has an active 1:1 mapping rule.

    Default-deny: empty, None, or unknown codes return False.
    Inactive rules (expert_pending, excluded) return False.
    Rules with multiple individual codes or components (1:N) return False —
    the legacy API cannot represent them as a single individual code.
    """
    if not ctp_code:
        return False
    rule = get_rule(ctp_code)
    if rule is None or not is_rule_active(rule):
        return False
    return rule.components is None and len(rule.individual_codes_s81) == 1


def get_individual_code_for_ctp(ctp_code: str | None) -> str | None:
    """Return the ``S21.G00.81.001`` individual code for an active 1:1 CTP.

    Returns ``None`` for empty, None, unmappable, inactive, or 1:N rules
    (rules with multiple codes or components cannot be faithfully represented
    as a single code).
    """
    if not ctp_code:
        return None
    rule = get_rule(ctp_code)
    if rule is None or not is_rule_active(rule):
        return None
    if rule.components is not None or len(rule.individual_codes_s81) != 1:
        return None
    return rule.individual_codes_s81[0]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _rule_to_legacy(rule: UrssafMappingRule) -> UrssafIndividualMapping:
    return UrssafIndividualMapping(
        ctp_code=rule.ctp_code,
        ctp_label=rule.ctp_label,
        individual_code_s81=rule.individual_codes_s81[0],
        ops_rule=rule.ops_rule,
        source_ref=", ".join(rule.source_refs) if rule.source_refs else "",
    )
