"""DSN enumeration label maps."""

from __future__ import annotations

# S21.G00.40.003 — Code statut categoriel Retraite Complementaire obligatoire
RETIREMENT_CATEGORY_LABELS: dict[str, str] = {
    "01": "cadre",
    "02": "extension_cadre",
    "04": "non_cadre",
    "98": "other_no_cadre_split",
    "99": "no_complementary_retirement",
}

# S21.G00.40.007 — Nature du contrat
CONTRACT_NATURE_LABELS: dict[str, str] = {
    "01": "cdi_prive",
    "02": "cdd_prive",
    "03": "ctt_interim",
    "07": "cdi_intermittent",
    "08": "cdd_usage",
    "09": "cdd_senior",
    "10": "cdd_objet_defini",
    "29": "convention_stage",
    "32": "cdd_remplacement",
    "50": "cdi_chantier",
    "60": "cdi_operationnel",
    "70": "cdi_interimaire",
    "80": "mandat_social",
    "81": "mandat_electif",
    "82": "contrat_appui",
    "89": "volontariat_service_civique",
    "90": "autre_contrat",
    "91": "contrat_engagement_educatif",
    "92": "cdd_tremplin",
    "93": "dispositif_academie_leaders",
}

# S21.G00.62.002 — Motif de rupture du contrat
CONTRACT_END_REASON_LABELS: dict[str, str] = {
    "011": "licenciement_liquidation_judiciaire",
    "012": "licenciement_redressement_judiciaire",
    "014": "licenciement_economique",
    "015": "licenciement_inaptitude_non_professionnelle",
    "017": "licenciement_inaptitude_professionnelle",
    "020": "licenciement_faute_grave",
    "025": "licenciement_faute_lourde",
    "026": "licenciement_cause_reelle_serieuse",
    "031": "fin_cdd",
    "032": "fin_mission_interim",
    "034": "fin_contrat_apprentissage",
    "035": "fin_periode_essai_initiative_salarie",
    "036": "fin_mandat",
    "038": "mise_retraite_employeur",
    "039": "depart_retraite_salarie",
    "043": "rupture_conventionnelle",
    "058": "prise_acte_rupture",
    "059": "demission",
    "065": "deces",
    "066": "depart_volontaire_pse",
    "099": "fin_relation_transfert",
}

# S21.G00.65.001 — Motif d'arrêt de travail
ABSENCE_MOTIF_LABELS: dict[str, str] = {
    "01": "maladie",
    "02": "maladie_professionnelle",
    "03": "accident_travail",
    "04": "accident_trajet",
    "05": "maternite",
    "06": "paternite",
    "07": "adoption",
    "10": "activite_partielle",
    "13": "conge_sans_solde",
    "14": "conge_sabbatique",
    "15": "conge_parental",
    "17": "evenement_familial",
    "19": "greve",
    "20": "temps_partiel_therapeutique",
    "501": "conge_divers_non_remunere",
    "637": "conge_evenement_familial",
}
