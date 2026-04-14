"""URSSAF CTP → individual-contribution mapping rules (V1 rule engine).

Canonical source of truth for which URSSAF CTP codes (``S21.G00.23.001``)
can be linked to employee-level individual contribution blocks
(``S21.G00.81.001``), under which conditions.

Replaces the former flat TSV lookup (``data/urssaf_individual_mapping.tsv``)
with a rule engine supporting:
- 1:N CTP-to-S81 mappings
- Component-scoped matching (qualifier → base code → S81 codes)
- Activation statuses (enabled, guarded, expert_pending, excluded)

The backward-compatible API is provided by
``dsn_extractor.urssaf_individual_mapping`` which delegates to this module.
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class UrssafMappingComponent:
    """One qualifier-scoped matching slice within a 1:N CTP rule.

    Binds a set of assiette qualifiers to the allowed S78 base codes
    and the S81 individual codes that may be matched under those bases.
    """

    assiette_qualifiers_s23: frozenset[str]
    base_codes_s78: frozenset[str]
    individual_codes_s81: tuple[str, ...]


@dataclass(frozen=True)
class UrssafMappingConditions:
    """Top-level conditions that gate whether the rule is evaluable at all."""

    requires_insee_commune: bool = False
    threshold_rule: str | None = None
    # Employee-level contract nature filtering (S21.G00.40.007).
    # requires_contract_nature: employee must have at least one of these values.
    # excludes_contract_nature: employee must NOT have any of these values.
    requires_contract_nature: frozenset[str] | None = None
    excludes_contract_nature: frozenset[str] | None = None
    # Sign-based gating on aggregated declared amount.
    # "negative" → CTP amount must be < 0; "positive" → must be > 0.
    sign_condition: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class UrssafMappingRule:
    """One CTP mapping rule with optional component-scoped matching."""

    ctp_code: str
    ctp_label: str
    cardinality: str  # "1:1" or "1:N"
    individual_codes_s81: tuple[str, ...]
    components: tuple[UrssafMappingComponent, ...] | None = None
    base_codes_s78: frozenset[str] | None = None  # For flat rules needing base code filter
    conditions: UrssafMappingConditions = UrssafMappingConditions()
    ops_rule: str = "urssaf_siret"
    confidence: str = "high"
    product_status: str = "enabled"  # enabled | guarded | expert_pending | excluded
    source_refs: tuple[str, ...] = ()
    # Reduction-family display/matching flag. When True:
    #   - UI renders declared, individual, delta as absolute magnitudes.
    #   - delta_within_unit (strict abs(delta) < 1.00€ policy) compares
    #     abs(declared) against abs(individual).
    #   - sign_condition is relaxed to an abs-value sanity check (the row
    #     still refuses when raw_declared is missing/0).
    # Signed amounts remain stored as-is for audit. Scoped to the known
    # reduction CTPs (003/004/668) — not a global convention.
    display_absolute: bool = False


# ---------------------------------------------------------------------------
# Allowed values
# ---------------------------------------------------------------------------

_VALID_PRODUCT_STATUSES = frozenset({"enabled", "guarded", "expert_pending", "excluded"})
_VALID_CARDINALITIES = frozenset({"1:1", "1:N"})
_ACTIVE_STATUSES = frozenset({"enabled", "guarded"})
_VALID_SIGN_CONDITIONS = frozenset({"negative", "positive"})


# ---------------------------------------------------------------------------
# V1 Rule data
# ---------------------------------------------------------------------------

_RULES: dict[str, UrssafMappingRule] = {
    # ---- CTP 100: Cotisations sociales RG (1:N, component-scoped) --------
    # Active only for employees who are NOT apprentice (02) and NOT mandataire (80).
    # Apprentice employees use CTP 726; mandataire employees use CTP 863.
    "100": UrssafMappingRule(
        ctp_code="100",
        ctp_label="RG CAS GENERAL",
        cardinality="1:N",
        individual_codes_s81=("045", "068", "074", "075", "076"),
        components=(
            UrssafMappingComponent(
                assiette_qualifiers_s23=frozenset({"920"}),
                base_codes_s78=frozenset({"03"}),
                individual_codes_s81=("045", "068", "074", "075", "076"),
            ),
            UrssafMappingComponent(
                assiette_qualifiers_s23=frozenset({"921"}),
                base_codes_s78=frozenset({"02"}),
                individual_codes_s81=("076",),
            ),
        ),
        conditions=UrssafMappingConditions(
            excludes_contract_nature=frozenset({"02", "80"}),
        ),
        confidence="high",
        product_status="enabled",
        source_refs=(
            "publicodes 13.1 L7-247 (base 03)",
            "publicodes 13.1 L402-480 (base 02)",
        ),
    ),
    # ---- CTP 959: Contribution formation professionnelle (1:1) -----------
    "959": UrssafMappingRule(
        ctp_code="959",
        ctp_label="CFP ENTREPRISE < 11 SALARIES",
        cardinality="1:1",
        individual_codes_s81=("128",),
        confidence="high",
        product_status="enabled",
        source_refs=("publicodes 13.1",),
    ),
    # ---- CTP 983: CFP intermittents du spectacle (1:1) -------------------
    "983": UrssafMappingRule(
        ctp_code="983",
        ctp_label="CFP INTERMITTENTS DU SPECTACLE",
        cardinality="1:1",
        individual_codes_s81=("128",),
        confidence="high",
        product_status="enabled",
        source_refs=("publicodes 13.1",),
    ),
    # ---- CTP 987: Contribution CPF CDD (1:1) ----------------------------
    "987": UrssafMappingRule(
        ctp_code="987",
        ctp_label="CONTRIBUTION CPF CDD",
        cardinality="1:1",
        individual_codes_s81=("129",),
        confidence="high",
        product_status="enabled",
        source_refs=("publicodes 13.1",),
    ),
    # ---- CTP 992: TA principale hors Alsace-Moselle (1:1) ----------------
    "992": UrssafMappingRule(
        ctp_code="992",
        ctp_label="TA PRINCIPALE HORS ALSACE MOSELLE",
        cardinality="1:1",
        individual_codes_s81=("130",),
        confidence="high",
        product_status="enabled",
        source_refs=("publicodes 13.1",),
    ),
    # ---- CTP 993: TA Alsace-Moselle (1:1) ---------------------------------
    "993": UrssafMappingRule(
        ctp_code="993",
        ctp_label="TA ALSACE MOSELLE",
        cardinality="1:1",
        individual_codes_s81=("130",),
        confidence="high",
        product_status="enabled",
        source_refs=("publicodes 13.1",),
    ),
    # ---- CTP 236: FNAL taux plein (1:1) -----------------------------------
    "236": UrssafMappingRule(
        ctp_code="236",
        ctp_label="FNAL TOTALITE",
        cardinality="1:1",
        individual_codes_s81=("049",),
        base_codes_s78=frozenset({"02"}),
        confidence="high",
        product_status="enabled",
        source_refs=("validation Thomas",),
    ),
    # ---- CTP 260: CSG CRDS régime général (1:N, sum 072+079) --------------
    "260": UrssafMappingRule(
        ctp_code="260",
        ctp_label="CSG CRDS REGIME GENERAL",
        cardinality="1:N",
        individual_codes_s81=("072", "079"),
        base_codes_s78=frozenset({"04"}),
        confidence="high",
        product_status="enabled",
        source_refs=("validation Thomas",),
    ),
    # ---- CTP 332: FNAL plafonné (1:1) -------------------------------------
    "332": UrssafMappingRule(
        ctp_code="332",
        ctp_label="FNAL PLAFONNE",
        cardinality="1:1",
        individual_codes_s81=("049",),
        base_codes_s78=frozenset({"02"}),
        confidence="high",
        product_status="enabled",
        source_refs=("validation Thomas",),
    ),
    # ---- CTP 423: Contrib assurance chômage apprentis (1:1) ---------------
    "423": UrssafMappingRule(
        ctp_code="423",
        ctp_label="CONTRIB ASSURANCE CHOMAGE APPREN 87 U2",
        cardinality="1:1",
        individual_codes_s81=("040",),
        base_codes_s78=frozenset({"07"}),
        conditions=UrssafMappingConditions(
            requires_contract_nature=frozenset({"02"}),
        ),
        confidence="high",
        product_status="enabled",
        source_refs=("validation Thomas",),
    ),
    # ---- CTP 635: Complément cotisation maladie (1:1) --------------------
    "635": UrssafMappingRule(
        ctp_code="635",
        ctp_label="COMPLEMENT COTISATION MALADIE",
        cardinality="1:1",
        individual_codes_s81=("907",),
        base_codes_s78=frozenset({"03"}),
        confidence="high",
        product_status="enabled",
        source_refs=("validation Thomas",),
    ),
    # ---- CTP 668: Réduction générale étendue (sign-gated, negative) ----
    "668": UrssafMappingRule(
        ctp_code="668",
        ctp_label="REDUCTION GENERALE ETENDUE U2",
        cardinality="1:1",
        individual_codes_s81=("018",),
        base_codes_s78=frozenset({"03"}),
        conditions=UrssafMappingConditions(
            sign_condition="negative",
        ),
        confidence="high",
        product_status="enabled",
        source_refs=("validation Thomas",),
        display_absolute=True,
    ),
    # ---- CTP 669: Régul réduction générale étendue (sign-gated, positive)
    "669": UrssafMappingRule(
        ctp_code="669",
        ctp_label="REGUL REDUCTION GENERALE ETENDUE U2",
        cardinality="1:1",
        individual_codes_s81=("018",),
        base_codes_s78=frozenset({"03"}),
        conditions=UrssafMappingConditions(
            sign_condition="positive",
        ),
        confidence="high",
        product_status="enabled",
        source_refs=("validation Thomas",),
    ),
    # ---- CTP 726: Apprentis secteur privé (1:N, component-scoped) ---------
    # Same component structure as CTP 100 but restricted to apprentice employees.
    "726": UrssafMappingRule(
        ctp_code="726",
        ctp_label="APPRENTIS SECT PRIVE INF SEUIL",
        cardinality="1:N",
        individual_codes_s81=("045", "068", "074", "075", "076"),
        components=(
            UrssafMappingComponent(
                assiette_qualifiers_s23=frozenset({"920"}),
                base_codes_s78=frozenset({"03"}),
                individual_codes_s81=("045", "068", "074", "075", "076"),
            ),
            UrssafMappingComponent(
                assiette_qualifiers_s23=frozenset({"921"}),
                base_codes_s78=frozenset({"02"}),
                individual_codes_s81=("076",),
            ),
        ),
        conditions=UrssafMappingConditions(
            requires_contract_nature=frozenset({"02"}),
        ),
        confidence="high",
        product_status="enabled",
        source_refs=("validation Thomas",),
    ),
    # ---- CTP 772: Contributions assurance chômage (1:1) -------------------
    "772": UrssafMappingRule(
        ctp_code="772",
        ctp_label="CONTRIBUTIONS ASSURANCE CHOMAGE U2",
        cardinality="1:1",
        individual_codes_s81=("040",),
        base_codes_s78=frozenset({"07"}),
        conditions=UrssafMappingConditions(
            excludes_contract_nature=frozenset({"02"}),
        ),
        confidence="high",
        product_status="enabled",
        source_refs=("validation Thomas",),
    ),
    # ---- CTP 863: RG mandataires sociaux (1:N, component-scoped) --------
    # Same component structure as CTP 100 but restricted to mandataire employees.
    "863": UrssafMappingRule(
        ctp_code="863",
        ctp_label="RG MANDATAIRES SOCIAUX",
        cardinality="1:N",
        individual_codes_s81=("045", "068", "074", "075", "076"),
        components=(
            UrssafMappingComponent(
                assiette_qualifiers_s23=frozenset({"920"}),
                base_codes_s78=frozenset({"03"}),
                individual_codes_s81=("045", "068", "074", "075", "076"),
            ),
            UrssafMappingComponent(
                assiette_qualifiers_s23=frozenset({"921"}),
                base_codes_s78=frozenset({"02"}),
                individual_codes_s81=("076",),
            ),
        ),
        conditions=UrssafMappingConditions(
            requires_contract_nature=frozenset({"80"}),
        ),
        confidence="high",
        product_status="enabled",
        source_refs=("validation Thomas",),
    ),
    # ---- CTP 937: Cotisations AGS cas général (1:1) -----------------------
    "937": UrssafMappingRule(
        ctp_code="937",
        ctp_label="COTISATIONS AGS CAS GENERAL U2",
        cardinality="1:1",
        individual_codes_s81=("048",),
        base_codes_s78=frozenset({"07"}),
        confidence="high",
        product_status="enabled",
        source_refs=("validation Thomas",),
    ),
    # ---- CTP 003: Réduction salariale heures sup (1:1) --------------------
    "003": UrssafMappingRule(
        ctp_code="003",
        ctp_label="REDUCTION SALARIALE HEURES SUP",
        cardinality="1:1",
        individual_codes_s81=("114",),
        base_codes_s78=frozenset({"03"}),
        confidence="high",
        product_status="enabled",
        source_refs=("validation Thomas",),
        display_absolute=True,
    ),
    # ---- CTP 004: Déduction patronale heures sup (1:1) --------------------
    "004": UrssafMappingRule(
        ctp_code="004",
        ctp_label="DEDUCTION PATRONALE HEURES SUP",
        cardinality="1:1",
        individual_codes_s81=("021",),
        base_codes_s78=frozenset({"03"}),
        confidence="high",
        product_status="enabled",
        source_refs=("validation Thomas",),
        display_absolute=True,
    ),
    # ---- CTP 027: Dialogue social (validated) -----------------------------
    "027": UrssafMappingRule(
        ctp_code="027",
        ctp_label="CONTRIBUTION AU DIALOGUE SOCIAL",
        cardinality="1:1",
        individual_codes_s81=("100",),
        base_codes_s78=frozenset({"03"}),
        confidence="high",
        product_status="enabled",
        source_refs=("publicodes 13.1 L235-247",),
    ),
    # ---- CTP 900: Versement mobilité — expert_pending --------------------
    "900": UrssafMappingRule(
        ctp_code="900",
        ctp_label="VERSEMENT MOBILITE",
        cardinality="1:1",
        individual_codes_s81=("081",),
        conditions=UrssafMappingConditions(
            requires_insee_commune=True,
            notes="Requires commune-scoped matching not available in V1.",
        ),
        confidence="high",
        product_status="expert_pending",
        source_refs=("publicodes 13.1",),
    ),
    # ---- CTP 901: Versement mobilité additionnel — expert_pending --------
    "901": UrssafMappingRule(
        ctp_code="901",
        ctp_label="VERSEMENT MOBILITE ADDITIONNEL",
        cardinality="1:1",
        individual_codes_s81=("082",),
        conditions=UrssafMappingConditions(
            requires_insee_commune=True,
            notes="Requires commune-scoped matching not available in V1.",
        ),
        confidence="high",
        product_status="expert_pending",
        source_refs=("publicodes 13.1",),
    ),
    # ---- CTP 971: CFP entreprise >= 11 salariés — expert_pending ----------
    "971": UrssafMappingRule(
        ctp_code="971",
        ctp_label="CFP ENTREPRISE >= 11 SALARIES",
        cardinality="1:1",
        individual_codes_s81=("128",),
        conditions=UrssafMappingConditions(
            threshold_rule="smic_threshold",
            notes="Threshold logic not implementable in V1.",
        ),
        confidence="high",
        product_status="expert_pending",
        source_refs=("publicodes 13.1",),
    ),
}


# ---------------------------------------------------------------------------
# Import-time validation
# ---------------------------------------------------------------------------

def _validate_rules(rules: dict[str, UrssafMappingRule]) -> None:
    """Fail fast on invalid rule data."""
    for key, rule in rules.items():
        if key != rule.ctp_code:
            raise RuntimeError(
                f"Rule key {key!r} != rule.ctp_code {rule.ctp_code!r}"
            )
        if not rule.ctp_code:
            raise RuntimeError("Empty ctp_code in rule")
        if not rule.individual_codes_s81:
            raise RuntimeError(
                f"Rule {rule.ctp_code}: empty individual_codes_s81"
            )
        if rule.product_status not in _VALID_PRODUCT_STATUSES:
            raise RuntimeError(
                f"Rule {rule.ctp_code}: invalid product_status "
                f"{rule.product_status!r}"
            )
        if rule.cardinality not in _VALID_CARDINALITIES:
            raise RuntimeError(
                f"Rule {rule.ctp_code}: invalid cardinality "
                f"{rule.cardinality!r}"
            )
        if rule.product_status == "guarded":
            has_condition = (
                rule.conditions.requires_insee_commune
                or rule.conditions.threshold_rule is not None
            )
            if not has_condition:
                raise RuntimeError(
                    f"Rule {rule.ctp_code}: guarded status requires "
                    f"at least one non-trivial condition"
                )
        if rule.conditions.sign_condition is not None:
            if rule.conditions.sign_condition not in _VALID_SIGN_CONDITIONS:
                raise RuntimeError(
                    f"Rule {rule.ctp_code}: invalid sign_condition "
                    f"{rule.conditions.sign_condition!r}"
                )
        if rule.base_codes_s78 is not None and rule.components is not None:
            raise RuntimeError(
                f"Rule {rule.ctp_code}: base_codes_s78 and components "
                f"are mutually exclusive"
            )
        if rule.components is not None:
            component_codes: set[str] = set()
            for comp in rule.components:
                if not comp.assiette_qualifiers_s23:
                    raise RuntimeError(
                        f"Rule {rule.ctp_code}: component has empty "
                        f"assiette_qualifiers_s23"
                    )
                if not comp.base_codes_s78:
                    raise RuntimeError(
                        f"Rule {rule.ctp_code}: component has empty "
                        f"base_codes_s78"
                    )
                if not comp.individual_codes_s81:
                    raise RuntimeError(
                        f"Rule {rule.ctp_code}: component has empty "
                        f"individual_codes_s81"
                    )
                component_codes.update(comp.individual_codes_s81)
            rule_codes = set(rule.individual_codes_s81)
            if component_codes != rule_codes:
                raise RuntimeError(
                    f"Rule {rule.ctp_code}: individual_codes_s81 "
                    f"{rule_codes} != union of component codes "
                    f"{component_codes}"
                )


_validate_rules(_RULES)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_rule(ctp_code: str | None) -> UrssafMappingRule | None:
    """Return the mapping rule for a CTP code, or None.

    Returns rules of any ``product_status``. The caller decides how
    to handle inactive rules.
    """
    if not ctp_code:
        return None
    return _RULES.get(ctp_code)


def is_rule_active(rule: UrssafMappingRule) -> bool:
    """Return True if the rule's product_status is active (enabled or guarded)."""
    return rule.product_status in _ACTIVE_STATUSES


def all_rules() -> dict[str, UrssafMappingRule]:
    """Return a copy of all declared rules (any status)."""
    return dict(_RULES)
