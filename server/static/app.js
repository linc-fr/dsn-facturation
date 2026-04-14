(function () {
  "use strict";

  // ── Enum labels (mirrors dsn_extractor/enums.py) ─────────
  var RETIREMENT_LABELS = {
    "01": "Cadre",
    "02": "Extension cadre",
    "04": "Non-cadre",
    "98": "Autre (pas de distinction cadre/non-cadre)",
    "99": "Pas de retraite compl\u00e9mentaire",
  };

  var CONTRACT_LABELS = {
    "01": "CDI",
    "02": "CDD",
    "03": "CTT (int\u00e9rim)",
    "07": "CDI intermittent",
    "08": "CDD d\u2019usage",
    "09": "CDD senior",
    "10": "CDD \u00e0 objet d\u00e9fini",
    "29": "Convention de stage",
    "32": "CDD remplacement",
    "50": "CDI de chantier",
    "60": "CDI op\u00e9rationnel",
    "70": "CDI int\u00e9rimaire",
    "80": "Mandat social",
    "81": "Mandat \u00e9lectif",
    "82": "Contrat d\u2019appui",
    "89": "Volontariat de service civique",
    "90": "Autre contrat",
    "91": "Contrat engagement \u00e9ducatif",
    "92": "CDD tremplin",
    "93": "Dispositif acad\u00e9mie des leaders",
  };

  var EXIT_REASON_LABELS = {
    "011": "Licenciement (liquidation judiciaire)",
    "012": "Licenciement (redressement judiciaire)",
    "014": "Licenciement \u00e9conomique",
    "015": "Licenciement inaptitude (non pro.)",
    "017": "Licenciement inaptitude (pro.)",
    "020": "Licenciement faute grave",
    "025": "Licenciement faute lourde",
    "026": "Licenciement cause r\u00e9elle et s\u00e9rieuse",
    "031": "Fin de CDD",
    "032": "Fin de mission (int\u00e9rim)",
    "034": "Fin de contrat d\u2019apprentissage",
    "035": "Fin de p\u00e9riode d\u2019essai (salari\u00e9)",
    "036": "Fin de mandat",
    "038": "Mise \u00e0 la retraite",
    "039": "D\u00e9part retraite (salari\u00e9)",
    "043": "Rupture conventionnelle",
    "058": "Prise d\u2019acte de rupture",
    "059": "D\u00e9mission",
    "065": "D\u00e9c\u00e8s",
    "066": "D\u00e9part volontaire (PSE)",
    "099": "Fin de relation (transfert)",
  };

  var ABSENCE_MOTIF_LABELS = {
    "01": "Maladie",
    "02": "Maladie professionnelle",
    "03": "Accident du travail",
    "04": "Accident de trajet",
    "05": "Maternit\u00e9",
    "06": "Paternit\u00e9",
    "07": "Adoption",
    "10": "Activit\u00e9 partielle",
    "13": "Cong\u00e9 sans solde",
    "14": "Cong\u00e9 sabbatique",
    "15": "Cong\u00e9 parental",
    "17": "\u00c9v\u00e9nement familial",
    "19": "Gr\u00e8ve",
    "20": "Temps partiel th\u00e9rapeutique",
    "501": "Cong\u00e9 divers non r\u00e9mun\u00e9r\u00e9",
    "637": "Cong\u00e9 pour \u00e9v\u00e9nement familial",
  };

  var COMPLEXITY_WEIGHTS = {
    "bulletins": 1,
    "entries": 3,
    "exits": 3,
    "absence_events": 2,
    "dsn_anomalies": 5,
  };

  var COMPLEXITY_LABELS = {
    "bulletins": "Bulletins",
    "entries": "Entr\u00e9es",
    "exits": "Sorties",
    "absence_events": "Absences",
    "dsn_anomalies": "Anomalies DSN",
  };

  var MONTH_NAMES = [
    "Janvier", "F\u00e9vrier", "Mars", "Avril", "Mai", "Juin",
    "Juillet", "Ao\u00fbt", "Septembre", "Octobre", "Novembre", "D\u00e9cembre",
  ];

  var CONTRIBUTION_FAMILIES = ["urssaf", "pas", "prevoyance", "mutuelle", "retraite"];

  var CONTRIBUTION_FAMILY_LABELS = {
    "urssaf": "URSSAF",
    "pas": "PAS",
    "prevoyance": "Pr\u00e9voyance",
    "mutuelle": "Mutuelle",
    "retraite": "Retraite",
  };

  // UI tab layer above the backend-facing family layer. Prévoyance + Mutuelle
  // are merged at presentation level only — backend payloads still carry the
  // original item.family values.
  var CONTRIBUTION_TABS = ["urssaf", "pas", "retraite", "complementaires"];

  var TAB_FAMILIES = {
    "urssaf": ["urssaf"],
    "pas": ["pas"],
    "retraite": ["retraite"],
    "complementaires": ["prevoyance", "mutuelle"],
  };

  var CONTRIBUTION_TAB_LABELS = {
    "urssaf": "URSSAF",
    "pas": "PAS",
    "retraite": "Retraite",
    "complementaires": "Organismes compl\u00e9mentaires",
  };

  // ── State ────────────────────────────────────────────────
  var PAGES = ["tracking"]; // dsn-facturation: only the tracking/facturation page is exposed

  var state = {
    phase: "empty",
    data: null,
    error: null,
    scope: "global",
    activeEstIdx: 0,
    activeContributionTab: "urssaf",
    activePage: "tracking",
    contribFilterEcartsOnly: true,
    expandedContribItems: {},
    // Slice D: per-CTP expansion keyed by "{itemStableKey}:{ctp_code}".
    // Default (no entry) means "follow the écart auto-expand rule".
    expandedUrssafCtps: {},
    hasUploadAttempted: false,
    lastUploadFilename: null,
    lastUploadFileBase64: null,
    feedbackOpen: false,
    feedbackSubmitting: false,
    feedbackSuccess: false,
  };

  // ── DOM refs (cached once) ───────────────────────────────
  var $body = document.body;
  var $dropzone = document.getElementById("dropzone");
  var $fileInput = document.getElementById("file-input");
  var $browseBtn = document.getElementById("browse-btn");
  var $dropzoneLabel = document.getElementById("dropzone-label");
  var $dropzoneSublabel = document.getElementById("dropzone-sublabel");
  var $dropzoneError = document.getElementById("dropzone-error");
  var $spinner = document.getElementById("spinner");
  var $spinnerLabel = document.getElementById("spinner-label");
  var $feedbackButtons = document.querySelectorAll('[data-action="feedback"]');
  var $feedbackModal = document.getElementById("feedback-modal");
  var $feedbackForm = document.getElementById("feedback-form");
  var $feedbackFormView = document.getElementById("feedback-form-view");
  var $feedbackSuccessView = document.getElementById("feedback-success-view");
  var $feedbackCategory = document.getElementById("feedback-category");
  var $feedbackEmail = document.getElementById("feedback-email");
  var $feedbackPhone = document.getElementById("feedback-phone");
  var $feedbackMessage = document.getElementById("feedback-message");
  var $feedbackConsent = document.getElementById("feedback-consent");
  var $feedbackFormError = document.getElementById("feedback-form-error");
  var $feedbackClose = document.getElementById("feedback-close");
  var $feedbackCancel = document.getElementById("feedback-cancel");
  var $feedbackSubmit = document.getElementById("feedback-submit");
  var $feedbackDone = document.getElementById("feedback-done");

  var $errorDetail = document.getElementById("error-detail");
  var $errorWarnings = document.getElementById("error-warnings");

  var $headerCompany = document.getElementById("header-company");
  var $headerSiret = document.getElementById("header-siret");
  var $headerPeriod = document.getElementById("header-period");

  var $establishmentTabs = document.getElementById("establishment-tabs");
  var $establishmentDetail = document.getElementById("establishment-detail");

  var $warningsBanner = document.getElementById("warnings-banner");
  var $warningsList = document.getElementById("warnings-list");

  var $cardEmployees = document.getElementById("card-employees");
  var $cardHires = document.getElementById("card-hires");
  var $cardExits = document.getElementById("card-exits");
  var $cardStagiaires = document.getElementById("card-stagiaires");

  var $tableRetirement = document.getElementById("table-retirement");
  var $tableContract = document.getElementById("table-contract");

  var $amtTickets = document.getElementById("amt-tickets");
  var $amtTransportPublic = document.getElementById("amt-transport-public");
  var $amtTransportPersonal = document.getElementById("amt-transport-personal");

  var $extNetFiscal = document.getElementById("ext-net-fiscal");
  var $extNetPaid = document.getElementById("ext-net-paid");
  var $extPas = document.getElementById("ext-pas");
  var $extGross = document.getElementById("ext-gross");

  // Social analysis
  var $saEffectif = document.getElementById("sa-effectif");
  var $saEntrees = document.getElementById("sa-entrees");
  var $saSorties = document.getElementById("sa-sorties");
  var $saStagiaires = document.getElementById("sa-stagiaires");
  var $saCadre = document.getElementById("sa-cadre");
  var $saNonCadre = document.getElementById("sa-non-cadre");
  var $saTableContracts = document.getElementById("sa-table-contracts");
  var $saTableExitReasons = document.getElementById("sa-table-exit-reasons");
  var $saAbsEmployees = document.getElementById("sa-abs-employees");
  var $saAbsEvents = document.getElementById("sa-abs-events");
  var $saTableAbsences = document.getElementById("sa-table-absences");
  var $saNetVerse = document.getElementById("sa-net-verse");
  var $saNetFiscal = document.getElementById("sa-net-fiscal");
  var $saPas = document.getElementById("sa-pas");
  var $saAlertsSection = document.getElementById("sa-alerts-section");
  var $saAlertsCount = document.getElementById("sa-alerts-count");
  var $saAlertsList = document.getElementById("sa-alerts-list");

  // Payroll tracking
  var $ptBulletins = document.getElementById("pt-bulletins");
  var $ptEntries = document.getElementById("pt-entries");
  var $ptExits = document.getElementById("pt-exits");
  var $ptAbsences = document.getElementById("pt-absences");
  var $ptExceptional = document.getElementById("pt-exceptional");
  var $ptAnomalies = document.getElementById("pt-anomalies");
  var $ptScoreValue = document.getElementById("pt-score-value");
  var $ptScoreInputs = document.getElementById("pt-score-inputs");
  var $ptEntriesNames = document.getElementById("pt-entries-names");
  var $ptExitsNames = document.getElementById("pt-exits-names");
  var $ptAbsencesNames = document.getElementById("pt-absences-names");

  // Contribution comparisons
  var $ccTrustBanner = document.getElementById("cc-trust-banner");
  var $contribFamilyTabs = document.getElementById("contrib-family-tabs");
  var $contribFamilyPanels = document.getElementById("contrib-family-panels");

  // ── Formatting helpers ───────────────────────────────────

  var NOT_AVAILABLE = "N.C.";

  function formatAmount(v) {
    if (v == null) return NOT_AVAILABLE;
    var n = parseFloat(v);
    if (isNaN(n)) return NOT_AVAILABLE;
    return n.toLocaleString("fr-FR", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }) + " \u20ac";
  }

  function formatRate(v) {
    if (v == null) return NOT_AVAILABLE;
    var n = parseFloat(v);
    if (isNaN(n)) return NOT_AVAILABLE;
    return n.toLocaleString("fr-FR", {
      minimumFractionDigits: 0,
      maximumFractionDigits: 4,
    }) + " %";
  }

  function formatSiret(v) {
    if (!v) return NOT_AVAILABLE;
    var s = v.replace(/\s/g, "");
    if (s.length !== 14) return v;
    return s.slice(0, 3) + " " + s.slice(3, 6) + " " + s.slice(6, 9) + " " + s.slice(9);
  }

  function formatMonth(v) {
    if (!v) return NOT_AVAILABLE;
    var parts = v.split("-");
    if (parts.length !== 2) return v;
    var monthIdx = parseInt(parts[1], 10) - 1;
    if (monthIdx < 0 || monthIdx > 11) return v;
    return MONTH_NAMES[monthIdx] + " " + parts[0];
  }

  function escapeHtml(s) {
    var div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
  }

  function formatStatusLabel(status) {
    if (!status) return NOT_AVAILABLE;
    if (status === "ok") return "OK";
    if (status === "ecart") return "\u00c9cart";
    if (status === "declared_only") return "D\u00e9clar\u00e9 seul";
    if (status === "computed_only") return "Recalcul\u00e9 seul";
    if (status.indexOf("manquant") === 0) return status.replace(/_/g, " ");
    if (status === "non_rattache") return "Non rattach\u00e9";
    if (status === "non_calculable") return "Non calculable";
    return status.replace(/_/g, " ");
  }

  function formatDetailStatusLabel(detail) {
    if (detail.status !== "ecart") return formatStatusLabel(detail.status);
    var rm = !!detail.rate_mismatch;
    var am = !!detail.amount_mismatch;
    if (rm && am) return "\u00c9cart taux + montant";
    if (rm) return "\u00c9cart taux";
    if (am) return "\u00c9cart montant";
    return "\u00c9cart";
  }

  function renderDetailStatusCell(detail) {
    var status = detail.status || "non_calculable";
    if (status === "ok") {
      return '<span class="status-subtle status-subtle--ok" title="OK">&#10003;</span>';
    }
    if (status === "non_calculable") {
      return '<span class="status-subtle status-subtle--muted" title="Non calculable">NC</span>';
    }
    return '<span class="' + getStatusBadgeClass(status) + '">'
      + escapeHtml(formatDetailStatusLabel(detail))
      + '</span>';
  }

  function formatFamilyLabel(family) {
    return CONTRIBUTION_FAMILY_LABELS[family] || family || NOT_AVAILABLE;
  }

  function formatTabLabel(tab) {
    return CONTRIBUTION_TAB_LABELS[tab] || tab || NOT_AVAILABLE;
  }

  function getStatusBadgeClass(status) {
    return "status-badge status-badge--" + (status || "non_calculable");
  }

  function collectComparisonWarnings(item) {
    var warnings = [];
    if (item && Array.isArray(item.warnings)) {
      warnings = warnings.concat(item.warnings);
    }
    if (item && Array.isArray(item.details)) {
      item.details.forEach(function (detail) {
        if (detail && Array.isArray(detail.warnings) && detail.warnings.length > 0) {
          warnings = warnings.concat(detail.warnings);
        }
      });
    }
    // Slice D: surface warnings attached to URSSAF per-CTP breakdowns
    // (e.g. partial multi-assiette collapse) so they reach item-level
    // badges, tab-level worst-status, and the trust banner.
    if (item && Array.isArray(item.urssaf_code_breakdowns)) {
      item.urssaf_code_breakdowns.forEach(function (breakdown) {
        if (breakdown && Array.isArray(breakdown.warnings) && breakdown.warnings.length > 0) {
          warnings = warnings.concat(breakdown.warnings);
        }
      });
    }
    return warnings;
  }

  function countComparisonWarnings(items) {
    var seen = {};
    var count = 0;
    (items || []).forEach(function (item) {
      collectComparisonWarnings(item).forEach(function (warning) {
        var key = String(warning);
        if (!seen[key]) {
          seen[key] = true;
          count += 1;
        }
      });
    });
    return count;
  }

  function validateEmail(email) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email || "");
  }

  function normalizePhone(raw) {
    var digits = (raw || "").replace(/[\s.\-()]/g, "");
    if (/^0[1-9]\d{8}$/.test(digits)) {
      return "+33" + digits.slice(1);
    }
    if (/^\+?\d{10,15}$/.test(digits)) {
      return digits.charAt(0) === "+" ? digits : "+" + digits;
    }
    return digits;
  }

  function getThemeName() {
    return "light";
  }

  function getActiveQualityWarningCount() {
    if (!state.data || state.phase !== "results") return 0;
    if (state.scope === "global") {
      var globalWarnings = state.data.global_quality && state.data.global_quality.warnings;
      return Array.isArray(globalWarnings) ? globalWarnings.length : 0;
    }
    var activeEst = state.data.establishments[state.activeEstIdx];
    var estWarnings = activeEst && activeEst.quality && activeEst.quality.warnings;
    return Array.isArray(estWarnings) ? estWarnings.length : 0;
  }

  function getFeedbackContext() {
    var comparisonPayload = state.phase === "results" ? (getActiveContributionPayload() || {}) : {};
    var visiblePhase = state.phase === "results" ? "results" : "error";
    var visibleError = state.phase === "error" && state.error ? state.error.detail : null;
    var errorWarnings = state.phase === "error" && state.error && Array.isArray(state.error.warnings)
      ? state.error.warnings.length
      : 0;

    return {
      timestamp: new Date().toISOString(),
      phase: visiblePhase,
      filename: state.lastUploadFilename || (state.data && state.data.source_file) || null,
      active_page: state.activePage || null,
      scope: state.scope,
      active_contribution_tab: state.activeContributionTab || null,
      browser: navigator.userAgent || null,
      language: navigator.language || null,
      theme: getThemeName(),
      error_detail: visibleError,
      visible_warning_count: state.phase === "results" ? getActiveQualityWarningCount() : errorWarnings,
      comparison_ok_count: comparisonPayload.ok_count != null ? comparisonPayload.ok_count : null,
      comparison_mismatch_count: comparisonPayload.mismatch_count != null ? comparisonPayload.mismatch_count : null,
      comparison_warning_count: comparisonPayload.warning_count != null ? comparisonPayload.warning_count : null,
    };
  }

  function setFeedbackError(message) {
    $feedbackFormError.hidden = !message;
    $feedbackFormError.textContent = message || "";
  }

  function resetFeedbackForm() {
    $feedbackCategory.value = "";
    $feedbackEmail.value = "";
    $feedbackPhone.value = "";
    $feedbackMessage.value = "";
    $feedbackConsent.checked = false;
    setFeedbackError("");
  }

  function openFeedbackModal() {
    resetFeedbackForm();
    setState({ feedbackOpen: true, feedbackSubmitting: false, feedbackSuccess: false });
  }

  function closeFeedbackModal() {
    resetFeedbackForm();
    setState({ feedbackOpen: false, feedbackSubmitting: false, feedbackSuccess: false });
  }

  function renderFeedback() {
    var canShowFeedback = state.hasUploadAttempted && (state.phase === "results" || state.phase === "error");
    $feedbackButtons.forEach(function (btn) {
      btn.hidden = !canShowFeedback;
    });

    $feedbackFormView.hidden = state.feedbackSuccess;
    $feedbackSuccessView.hidden = !state.feedbackSuccess;

    var controlsDisabled = state.feedbackSubmitting;
    $feedbackCategory.disabled = controlsDisabled;
    $feedbackEmail.disabled = controlsDisabled;
    $feedbackPhone.disabled = controlsDisabled;
    $feedbackMessage.disabled = controlsDisabled;
    $feedbackConsent.disabled = controlsDisabled;
    $feedbackCancel.disabled = controlsDisabled;
    $feedbackClose.disabled = controlsDisabled;
    $feedbackSubmit.disabled = controlsDisabled;

    if (state.feedbackSubmitting) {
      $feedbackSubmit.textContent = "Envoi...";
    } else {
      $feedbackSubmit.textContent = "Envoyer";
    }

    if (state.feedbackOpen) {
      if (!$feedbackModal.open) {
        try {
          $feedbackModal.showModal();
        } catch (err) {
          console.warn("Impossible d'ouvrir la fenetre de retour", err);
        }
      }
    } else if ($feedbackModal.open) {
      $feedbackModal.close();
    }
  }

  async function submitFeedback(event) {
    event.preventDefault();

    var category = $feedbackCategory.value.trim();
    var email = $feedbackEmail.value.trim();
    var phone = normalizePhone($feedbackPhone.value);
    var message = $feedbackMessage.value.trim();
    var consent = $feedbackConsent.checked;

    if (!category || !message || !phone || !email) {
      setFeedbackError("Merci de remplir tous les champs demandés.");
      return;
    }
    if (!validateEmail(email)) {
      setFeedbackError("Merci de renseigner un email valide.");
      return;
    }
    if (phone.length < 10) {
      setFeedbackError("Merci de renseigner un numéro de téléphone valide.");
      return;
    }
    if (!consent) {
      setFeedbackError("Le consentement est requis pour envoyer votre retour.");
      return;
    }

    setFeedbackError("");
    setState({ feedbackSubmitting: true });

    try {
      var response = await fetch("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          category: category,
          message: message,
          email: email,
          phone: phone,
          consent: consent,
          context: getFeedbackContext(),
          file_base64: state.lastUploadFileBase64 || null,
          file_name: state.lastUploadFilename || null,
        }),
      });
      var payload = await response.json();
      if (!response.ok) {
        setFeedbackError(payload.detail || "L'envoi a échoué. Merci de réessayer.");
        setState({ feedbackSubmitting: false });
        return;
      }
      setState({ feedbackSubmitting: false, feedbackSuccess: true });
    } catch (err) {
      setFeedbackError("L'envoi a échoué. Merci de vérifier votre connexion puis de réessayer.");
      setState({ feedbackSubmitting: false });
    }
  }

  // ── State management ─────────────────────────────────────

  function setState(patch) {
    for (var k in patch) {
      if (patch.hasOwnProperty(k)) state[k] = patch[k];
    }
    render();
  }

  // ── Render ───────────────────────────────────────────────

  function render() {
    $body.dataset.state = state.phase;

    if (state.phase === "uploading") {
      $dropzoneLabel.textContent = "Traitement en cours...";
      $dropzoneSublabel.textContent = "";
      $browseBtn.hidden = true;
      $spinner.hidden = false;
      $spinnerLabel.hidden = false;
      $dropzoneError.textContent = "";
    } else if (state.phase === "empty") {
      $dropzoneLabel.textContent = "D\u00e9posez un fichier .dsn, .txt ou .edi ici";
      $dropzoneSublabel.textContent = "ou cliquez pour parcourir";
      $browseBtn.hidden = false;
      $spinner.hidden = true;
      $spinnerLabel.hidden = true;
    }

    if (state.phase === "error" && state.error) {
      renderError();
    }

    if (state.phase === "results" && state.data) {
      renderResults();
    }

    renderFeedback();
  }

  // ── Error rendering ──────────────────────────────────────

  function renderError() {
    var err = state.error;
    $errorDetail.textContent = err.detail || "Une erreur inconnue s\u2019est produite.";
    $errorWarnings.innerHTML = "";
    if (err.warnings && err.warnings.length > 0) {
      err.warnings.forEach(function (w) {
        var li = document.createElement("li");
        li.textContent = w;
        $errorWarnings.appendChild(li);
      });
    }
  }

  // ── Results rendering ────────────────────────────────────

  function renderPageNav() {
    var btns = document.querySelectorAll(".page-nav__btn");
    btns.forEach(function (btn) {
      if (btn.dataset.page === state.activePage) {
        btn.classList.add("page-nav__btn--active");
      } else {
        btn.classList.remove("page-nav__btn--active");
      }
    });

    PAGES.forEach(function (page) {
      var el = document.getElementById("page-" + page);
      if (el) el.hidden = page !== state.activePage;
    });
  }

  function renderResults() {
    var d = state.data;

    renderHeader(d);
    renderPageNav();
    renderScopeToggle();
    renderEstablishmentTabs(d);

    var counts, amounts, extras, quality;

    if (state.scope === "global") {
      counts = d.global_counts;
      amounts = d.global_amounts;
      extras = d.global_extras;
      quality = d.global_quality;
      $establishmentDetail.hidden = true;
    } else {
      var est = d.establishments[state.activeEstIdx];
      counts = est.counts;
      amounts = est.amounts;
      extras = est.extras;
      quality = est.quality;
      renderEstablishmentDetail(est.identity);
    }

    renderSummaryCards(counts);
    renderRetirementTable(counts);
    renderContractTable(counts);
    renderAmounts(amounts);
    renderExtras(extras);
    renderWarnings(quality);

    var sa, pt;
    if (state.scope === "global") {
      sa = d.global_social_analysis;
      pt = d.global_payroll_tracking;
    } else {
      var activeEst = d.establishments[state.activeEstIdx];
      sa = activeEst.social_analysis;
      pt = activeEst.payroll_tracking;
    }
    renderSocialAnalysis(sa);
    renderPayrollTracking(pt);
    renderContributionComparisons();
  }

  function renderHeader(d) {
    var company = d.company || {};
    $headerCompany.textContent = company.name || company.siren || "Entreprise";
    $headerSiret.textContent = formatSiret(company.siret);
    $headerPeriod.textContent = formatMonth(d.declaration ? d.declaration.month : null);
  }

  function renderScopeToggle() {
    var btns = document.querySelectorAll(".scope-toggle__btn");
    btns.forEach(function (btn) {
      if (btn.dataset.scope === state.scope) {
        btn.classList.add("scope-toggle__btn--active");
      } else {
        btn.classList.remove("scope-toggle__btn--active");
      }
    });

    // Disable per-establishment if no establishments
    var estBtn = document.querySelector('[data-scope="establishment"]');
    if (state.data && state.data.establishments.length === 0) {
      estBtn.disabled = true;
      estBtn.style.opacity = "0.4";
      estBtn.style.cursor = "default";
    } else {
      estBtn.disabled = false;
      estBtn.style.opacity = "";
      estBtn.style.cursor = "";
    }
  }

  function renderEstablishmentTabs(d) {
    var show = state.scope === "establishment" && d.establishments.length > 1;
    $establishmentTabs.hidden = !show;
    if (!show) return;

    $establishmentTabs.innerHTML = "";
    d.establishments.forEach(function (est, i) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "tab-bar__btn";
      if (i === state.activeEstIdx) btn.classList.add("tab-bar__btn--active");
      btn.dataset.index = i;
      var id = est.identity || {};
      btn.textContent = id.name || id.siret || ("\u00c9tablissement " + (i + 1));
      $establishmentTabs.appendChild(btn);
    });
  }

  function renderEstablishmentDetail(identity) {
    if (!identity) {
      $establishmentDetail.hidden = true;
      return;
    }

    var items = [];
    if (identity.siret) items.push({ label: "SIRET", value: formatSiret(identity.siret) });
    if (identity.naf_code) items.push({ label: "NAF", value: identity.naf_code });
    if (identity.ccn_code) items.push({ label: "CCN", value: identity.ccn_code });
    if (identity.city) items.push({ label: "Ville", value: identity.city });

    if (items.length === 0) {
      $establishmentDetail.hidden = true;
      return;
    }

    $establishmentDetail.hidden = false;
    $establishmentDetail.innerHTML = items.map(function (item) {
      return '<span class="establishment-detail__item">'
        + '<span class="establishment-detail__label">' + escapeHtml(item.label) + ':</span> '
        + '<span class="establishment-detail__value">' + escapeHtml(item.value) + '</span>'
        + '</span>';
    }).join("");
  }

  function renderSummaryCards(counts) {
    $cardEmployees.textContent = counts.employee_blocks_count;
    $cardHires.textContent = counts.new_employees_in_month;
    $cardExits.textContent = counts.exiting_employees_in_month;
    $cardStagiaires.textContent = counts.stagiaires;
  }

  function renderRetirementTable(counts) {
    var data = counts.employees_by_retirement_category_code || {};
    var codes = Object.keys(data);

    if (codes.length === 0) {
      $tableRetirement.innerHTML = '<tr><td colspan="3" class="data-table__empty">Aucune donn\u00e9e</td></tr>';
      return;
    }

    codes.sort();
    $tableRetirement.innerHTML = codes.map(function (code) {
      var label = RETIREMENT_LABELS[code] || code;
      return '<tr>'
        + '<td class="mono">' + escapeHtml(code) + '</td>'
        + '<td>' + escapeHtml(label) + '</td>'
        + '<td>' + data[code] + '</td>'
        + '</tr>';
    }).join("");
  }

  function renderContractTable(counts) {
    var data = counts.employees_by_contract_nature_code || {};
    var codes = Object.keys(data);

    if (codes.length === 0) {
      $tableContract.innerHTML = '<tr><td colspan="3" class="data-table__empty">Aucune donn\u00e9e</td></tr>';
      return;
    }

    codes.sort();
    $tableContract.innerHTML = codes.map(function (code) {
      var label = CONTRACT_LABELS[code] || code;
      return '<tr>'
        + '<td class="mono">' + escapeHtml(code) + '</td>'
        + '<td>' + escapeHtml(label) + '</td>'
        + '<td>' + data[code] + '</td>'
        + '</tr>';
    }).join("");
  }

  function renderAmounts(amounts) {
    $amtTickets.textContent = formatAmount(amounts.tickets_restaurant_employer_contribution_total);
    $amtTransportPublic.textContent = formatAmount(amounts.transport_public_total);
    $amtTransportPersonal.textContent = formatAmount(amounts.transport_personal_total);
  }

  function renderExtras(extras) {
    $extNetFiscal.textContent = formatAmount(extras.net_fiscal_sum);
    $extNetPaid.textContent = formatAmount(extras.net_paid_sum);
    $extPas.textContent = formatAmount(extras.pas_sum);
    $extGross.textContent = formatAmount(extras.gross_sum_from_salary_bases);
  }

  function renderWarnings(quality) {
    var warnings = quality.warnings || [];
    if (warnings.length === 0) {
      $warningsBanner.hidden = true;
      return;
    }
    $warningsBanner.hidden = false;
    $warningsList.innerHTML = "";
    warnings.forEach(function (w) {
      var li = document.createElement("li");
      li.textContent = w;
      $warningsList.appendChild(li);
    });
  }

  // ── Social analysis rendering ──────────────────────────────

  function renderSocialAnalysis(sa) {
    if (!sa) return;

    $saEffectif.textContent = sa.effectif;
    $saEntrees.textContent = sa.entrees;
    $saSorties.textContent = sa.sorties;
    $saStagiaires.textContent = sa.stagiaires;
    $saCadre.textContent = sa.cadre_count;
    $saNonCadre.textContent = sa.non_cadre_count;

    // Contracts table
    renderCodeTable($saTableContracts, sa.contracts_by_code, CONTRACT_LABELS);

    // Exit reasons table
    renderCodeTable($saTableExitReasons, sa.exit_reasons_by_code, EXIT_REASON_LABELS);

    // Absences
    $saAbsEmployees.textContent = sa.absences_employees_count;
    $saAbsEvents.textContent = sa.absences_events_count;
    renderCodeCountTable($saTableAbsences, sa.absences_by_code, ABSENCE_MOTIF_LABELS);

    // Remuneration
    $saNetVerse.textContent = formatAmount(sa.net_verse_total);
    $saNetFiscal.textContent = formatAmount(sa.net_fiscal_total);
    $saPas.textContent = formatAmount(sa.pas_total);

    // Quality alerts
    var alerts = sa.quality_alerts || [];
    if (alerts.length === 0) {
      $saAlertsSection.hidden = true;
    } else {
      $saAlertsSection.hidden = false;
      $saAlertsCount.textContent = sa.quality_alerts_count;
      $saAlertsList.innerHTML = "";
      alerts.forEach(function (a) {
        var li = document.createElement("li");
        li.textContent = a;
        $saAlertsList.appendChild(li);
      });
    }
  }

  function renderCodeTable(tbody, codeData, labelMap) {
    var codes = Object.keys(codeData || {});
    if (codes.length === 0) {
      tbody.innerHTML = '<tr><td colspan="3" class="data-table__empty">Aucune donn\u00e9e</td></tr>';
      return;
    }
    codes.sort();
    tbody.innerHTML = codes.map(function (code) {
      var label = labelMap[code] || code;
      return '<tr>'
        + '<td class="mono">' + escapeHtml(code) + '</td>'
        + '<td>' + escapeHtml(label) + '</td>'
        + '<td>' + codeData[code] + '</td>'
        + '</tr>';
    }).join("");
  }

  function renderCodeCountTable(tbody, codeData, labelMap) {
    var codes = Object.keys(codeData || {});
    if (codes.length === 0) {
      tbody.innerHTML = '<tr><td colspan="2" class="data-table__empty">Aucune donn\u00e9e</td></tr>';
      return;
    }
    codes.sort();
    tbody.innerHTML = codes.map(function (code) {
      var label = labelMap[code] || code;
      return '<tr>'
        + '<td>' + escapeHtml(label) + ' <span class="mono">(' + escapeHtml(code) + ')</span></td>'
        + '<td>' + codeData[code] + '</td>'
        + '</tr>';
    }).join("");
  }

  function renderNameList(el, names) {
    if (!names || names.length === 0) { el.innerHTML = ""; return; }
    el.innerHTML = names.map(function (n) {
      return '<span class="name-tag">' + escapeHtml(n) + '</span>';
    }).join("");
  }

  function renderAbsenceDetails(el, details) {
    if (!details || details.length === 0) { el.innerHTML = ""; return; }
    el.innerHTML = details.map(function (d) {
      var motif = ABSENCE_MOTIF_LABELS[d.motif_code] || d.motif_label || d.motif_code;
      return '<span class="name-tag">'
        + escapeHtml(d.employee_name)
        + ' <span class="name-tag__motif">\u00b7 ' + escapeHtml(motif) + '</span>'
        + '</span>';
    }).join("");
  }

  // ── Payroll tracking rendering ─────────────────────────────

  function renderPayrollTracking(pt) {
    if (!pt) return;

    $ptBulletins.textContent = pt.bulletins;
    $ptEntries.textContent = pt.billable_entries;
    $ptExits.textContent = pt.billable_exits;
    $ptAbsences.textContent = pt.billable_absence_events;
    $ptAnomalies.textContent = pt.dsn_anomalies_count;

    renderNameList($ptEntriesNames, pt.billable_entry_names);
    renderNameList($ptExitsNames, pt.billable_exit_names);
    renderAbsenceDetails($ptAbsencesNames, pt.billable_absence_details);

    $ptScoreValue.textContent = pt.complexity_score;

    var inputs = pt.complexity_inputs || {};
    var keys = ["bulletins", "entries", "exits", "absence_events", "dsn_anomalies"];
    $ptScoreInputs.innerHTML = keys.map(function (key) {
      var val = inputs[key] || 0;
      var weight = COMPLEXITY_WEIGHTS[key] || 0;
      var label = COMPLEXITY_LABELS[key] || key;
      return '<tr>'
        + '<td>' + escapeHtml(label) + '</td>'
        + '<td>' + val + '</td>'
        + '<td>\u00d7' + weight + '</td>'
        + '<td>' + (val * weight) + '</td>'
        + '</tr>';
    }).join("");
  }

  // ── Contribution comparisons rendering ───────────────────

  function getActiveContributionPayload() {
    if (!state.data) return null;
    if (state.scope === "global") return state.data.global_contribution_comparisons || null;
    var est = state.data.establishments[state.activeEstIdx];
    return est ? (est.contribution_comparisons || null) : null;
  }

  function renderContributionComparisons() {
    var payload = getActiveContributionPayload() || {};
    var items = Array.isArray(payload.items) ? payload.items : [];

    var okCount = payload.ok_count != null
      ? payload.ok_count
      : items.filter(function (item) { return item.status === "ok"; }).length;
    var mismatchCount = payload.mismatch_count != null
      ? payload.mismatch_count
      : items.filter(function (item) { return item.status === "ecart"; }).length;

    // Slice D: compute the warning count client-side over the full set of
    // warning sources (item + detail + urssaf_code_breakdowns). The backend
    // payload.warning_count is kept as a lower-bound fallback so stale
    // servers still produce a sensible number, but the client-side count
    // takes precedence whenever it sees more warnings — which is always the
    // case now that breakdown.warnings exists.
    var clientWarningCount = countComparisonWarnings(items);
    var warningCount = Math.max(payload.warning_count || 0, clientWarningCount);

    renderTrustBanner(okCount, mismatchCount, warningCount);
    renderContributionTabBar(items);
    renderContributionTabPanels(items);
  }

  function renderTrustBanner(okCount, mismatchCount, warningCount) {
    var trustLevel, verdict;
    if (mismatchCount > 0) {
      trustLevel = "alert";
      verdict = "\u00c9carts d\u00e9tect\u00e9s";
    } else if (warningCount > 0) {
      trustLevel = "review";
      verdict = "Points de vigilance";
    } else {
      trustLevel = "trusted";
      verdict = "DSN conforme";
    }

    var iconMap = { trusted: "&#10003;", review: "&#9888;", alert: "&#10007;" };

    $ccTrustBanner.innerHTML = '<div class="trust-banner trust-banner--' + trustLevel + '">'
      + '<div class="trust-banner__verdict">'
      + '<span class="trust-banner__icon">' + iconMap[trustLevel] + '</span>'
      + '<span class="trust-banner__label">' + verdict + '</span>'
      + '</div>'
      + '<div class="trust-banner__counts">'
      + '<span class="trust-count trust-count--ok">' + okCount + ' OK</span>'
      + '<span class="trust-banner__sep">\u00b7</span>'
      + '<span class="trust-count trust-count--ecart">' + mismatchCount + ' \u00e9cart(s)</span>'
      + '<span class="trust-banner__sep">\u00b7</span>'
      + '<span class="trust-count trust-count--warning">' + warningCount + ' avert.</span>'
      + '</div>'
      + '</div>';
  }

  function getInitialContributionTab(data) {
    var payload = (data && data.global_contribution_comparisons) || {};
    var items = Array.isArray(payload.items) ? payload.items : [];
    var meta = computeTabMeta(items);
    var statusOrder = { ecart: 0, warning: 1, ok: 2, empty: 3 };
    var best = "urssaf";
    var bestRank = 3;
    CONTRIBUTION_TABS.forEach(function (t) {
      var rank = statusOrder[meta[t].worstStatus] || 3;
      if (rank < bestRank) { bestRank = rank; best = t; }
    });
    return best;
  }

  function computeTabMeta(items) {
    // Build reverse map family → tab once per call.
    var familyToTab = {};
    CONTRIBUTION_TABS.forEach(function (tab) {
      (TAB_FAMILIES[tab] || []).forEach(function (family) {
        familyToTab[family] = tab;
      });
    });

    var meta = {};
    CONTRIBUTION_TABS.forEach(function (t) {
      meta[t] = { count: 0, ecartCount: 0, warningCount: 0, worstStatus: "empty" };
    });
    (items || []).forEach(function (item) {
      var family = item && item.family ? item.family : "";
      var tab = familyToTab[family];
      if (!tab || !meta[tab]) return;
      meta[tab].count++;
      if (item.status === "ecart") meta[tab].ecartCount++;
      var w = collectComparisonWarnings(item);
      if (w.length > 0) meta[tab].warningCount++;
    });
    CONTRIBUTION_TABS.forEach(function (t) {
      var m = meta[t];
      if (m.count === 0) m.worstStatus = "empty";
      else if (m.ecartCount > 0) m.worstStatus = "ecart";
      else if (m.warningCount > 0) m.worstStatus = "warning";
      else m.worstStatus = "ok";
    });
    return meta;
  }

  function renderContributionTabBar(items) {
    var tabMeta = computeTabMeta(items);

    // Fixed order: URSSAF, PAS, Retraite, Organismes complémentaires
    $contribFamilyTabs.innerHTML = CONTRIBUTION_TABS.map(function (tab) {
      var active = tab === state.activeContributionTab;
      var m = tabMeta[tab];
      var dotClass = 'family-dot family-dot--' + m.worstStatus;
      return '<button type="button" class="tab-bar__btn'
        + (active ? ' tab-bar__btn--active' : '')
        + '" data-tab="' + escapeHtml(tab) + '">'
        + '<span class="' + dotClass + '"></span>'
        + escapeHtml(formatTabLabel(tab))
        + ' (' + m.count + ')'
        + '</button>';
    }).join("");
  }

  function renderContributionTabPanels(items) {
    var byTab = {};
    CONTRIBUTION_TABS.forEach(function (tab) {
      byTab[tab] = [];
    });

    // Reverse map family → tab for routing items into tab buckets.
    var familyToTab = {};
    CONTRIBUTION_TABS.forEach(function (tab) {
      (TAB_FAMILIES[tab] || []).forEach(function (family) {
        familyToTab[family] = tab;
      });
    });

    (items || []).forEach(function (item) {
      var family = item && item.family ? item.family : "";
      var tab = familyToTab[family];
      if (tab && byTab[tab]) byTab[tab].push(item);
    });

    var html = CONTRIBUTION_TABS.map(function (tab) {
      var tabItems = byTab[tab] || [];
      var hidden = tab !== state.activeContributionTab;
      return '<section class="contrib-panel"' + (hidden ? ' hidden' : '') + '>'
        + renderContributionTabPanelContent(tab, tabItems)
        + '</section>';
    }).join("");

    // Render unclassified items (family not mapped to any tab via TAB_FAMILIES).
    // prevoyance/mutuelle MUST NOT fall here because TAB_FAMILIES.complementaires covers them.
    var unclassifiedItems = [];
    (items || []).forEach(function (item) {
      var family = item && item.family ? item.family : "";
      if (family && !familyToTab[family]) {
        unclassifiedItems.push(item);
      }
    });
    if (unclassifiedItems.length > 0) {
      html += '<section class="contrib-panel">'
        + '<h3 class="data-section__title">Organismes non classifi\u00e9s (' + unclassifiedItems.length + ')</h3>'
        + '<div class="contrib-stack">' + unclassifiedItems.map(renderContributionItem).join("") + '</div>'
        + '</section>';
    }

    $contribFamilyPanels.innerHTML = html;
  }

  function renderContributionTabPanelContent(tab, items) {
    if (!items || items.length === 0) {
      return '<div class="contrib-empty">'
        + '<strong>' + escapeHtml(formatTabLabel(tab)) + '</strong>'
        + 'Aucune donn\u00e9e disponible pour cet onglet dans le r\u00e9sultat courant.'
        + '</div>';
    }

    var allOk = items.every(function (item) { return item.status === "ok" && collectComparisonWarnings(item).length === 0; });
    var hint = allOk
      ? '<div class="contrib-all-ok-hint">Tous les organismes sont conformes. Cliquez pour voir le d\u00e9tail.</div>'
      : '';

    return '<div class="contrib-stack">' + items.map(renderContributionItem).join("") + '</div>' + hint;
  }

  function getItemStableKey(item) {
    return (item.family || "") + ":" + (item.organism_id || "") + ":" + (item.contract_ref || "") + ":" + (item.adhesion_id || "");
  }

  function getItemDefaultExpanded(item) {
    return true;
  }

  function isItemExpanded(item) {
    var key = getItemStableKey(item);
    if (state.expandedContribItems.hasOwnProperty(key)) {
      return state.expandedContribItems[key];
    }
    return getItemDefaultExpanded(item);
  }

  function renderContributionSummaryMetrics(item) {
    var parts = [];
    var deltas = [
      { label: "\u0394 agr./bord.", value: item.aggregate_vs_bordereau_delta },
      { label: "\u0394 agr./comp.", value: item.aggregate_vs_component_delta },
      { label: "\u0394 bord./comp.", value: item.bordereau_vs_component_delta },
      { label: "\u0394 agr./ind.", value: item.aggregate_vs_individual_delta },
    ];
    deltas.forEach(function (d) {
      if (d.value != null) {
        var n = parseFloat(d.value);
        if (!isNaN(n) && n !== 0) {
          parts.push('<span class="contrib-metric contrib-metric--ecart">'
            + escapeHtml(d.label) + ' ' + escapeHtml(formatAmount(d.value)) + '</span>');
        }
      }
    });
    if (parts.length === 0 && item.aggregate_amount != null) {
      parts.push('<span class="contrib-metric">'
        + escapeHtml(formatAmount(item.aggregate_amount)) + '</span>');
    }
    return parts.join('<span class="contrib-metric-sep">\u00b7</span>');
  }

  function renderContributionItem(item) {
    var title = item.organism_label || item.organism_id || formatFamilyLabel(item.family);
    var itemKey = getItemStableKey(item);
    var expanded = isItemExpanded(item);
    var defaultExpanded = getItemDefaultExpanded(item);

    // Full metadata for tooltip (always complete)
    var fullMeta = [];
    if (item.organism_id) fullMeta.push("Organisme : " + item.organism_id);
    if (item.contract_ref) fullMeta.push("Contrat : " + item.contract_ref);
    if (item.adhesion_id) fullMeta.push("Adh\u00e9sion : " + item.adhesion_id);
    var titleAttr = fullMeta.length > 0 ? ' title="' + escapeHtml(fullMeta.join(' \u00b7 ')) + '"' : '';

    // Visible metadata (scope-aware)
    var meta = [];
    if (item.organism_id && item.organism_id !== item.organism_label) {
      meta.push("Organisme : " + item.organism_id);
    }
    if (state.scope !== "global") {
      if (item.contract_ref) meta.push("Contrat : " + item.contract_ref);
      if (item.adhesion_id) meta.push("Adh\u00e9sion : " + item.adhesion_id);
    }

    // Primary delta for header
    var primaryDelta = item.aggregate_vs_bordereau_delta
      || item.aggregate_vs_component_delta
      || item.bordereau_vs_component_delta
      || item.aggregate_vs_individual_delta
      || null;
    var deltaHtml = '';
    if (primaryDelta != null && item.status === 'ecart') {
      var deltaVal = parseFloat(primaryDelta);
      if (!isNaN(deltaVal) && deltaVal !== 0) {
        deltaHtml = '<span class="contrib-item__delta">'
          + escapeHtml(formatAmount(primaryDelta))
          + '</span>';
      }
    }

    // Total warning count (item + detail level) for summary badge
    var allWarnings = collectComparisonWarnings(item);
    var warningCountHtml = allWarnings.length > 0
      ? '<span class="contrib-summary__warning-count">' + allWarnings.length + ' avert.</span>'
      : '';

    // Item-level warnings only for the warning box (detail warnings go inline in table)
    var itemWarnings = Array.isArray(item.warnings) ? item.warnings : [];

    return '<article class="contrib-item' + (expanded ? ' contrib-item--expanded' : '') + '"'
      + ' data-item-id="' + escapeHtml(itemKey) + '"'
      + ' data-status="' + (item.status || 'non_calculable') + '"'
      + ' data-default-expanded="' + (defaultExpanded ? 'true' : 'false') + '">'
      + '<div class="contrib-summary" data-action="toggle-detail"' + titleAttr + '>'
      + '<div class="contrib-summary__left">'
      + '<span class="contrib-summary__chevron">&#9654;</span>'
      + '<div>'
      + '<div class="contrib-item__title">' + escapeHtml(title) + '</div>'
      + (meta.length > 0
        ? '<div class="contrib-item__meta">' + escapeHtml(meta.join(' \u00b7 ')) + '</div>'
        : '')
      + '</div>'
      + '</div>'
      + '<div class="contrib-item__header-right">'
      + '<div class="contrib-summary__metrics">' + renderContributionSummaryMetrics(item) + '</div>'
      + warningCountHtml
      + deltaHtml
      + '<span class="' + getStatusBadgeClass(item.status) + '">'
      + escapeHtml(formatStatusLabel(item.status))
      + '</span>'
      + '</div>'
      + '</div>'
      + '<div class="contrib-detail-body' + (expanded ? '' : ' contrib-detail-body--collapsed') + '">'
      + (itemWarnings.length > 0 ? renderContributionWarnings(itemWarnings) : '')
      + renderContributionMetrics(item)
      + renderContributionDetailsTable(item)
      + '</div>'
      + '</article>';
  }

  function renderContributionMetrics(item) {
    var rows = [
      { label: "Agr\u00e9g\u00e9", value: formatAmount(item.aggregate_amount) },
      { label: "Bordereau", value: formatAmount(item.bordereau_amount) },
      { label: "Composant", value: formatAmount(item.component_amount) },
      { label: "Individuel", value: formatAmount(item.individual_amount) },
      { label: "\u0394 agr\u00e9g\u00e9 / bordereau", value: formatAmount(item.aggregate_vs_bordereau_delta) },
      { label: "\u0394 bordereau / composant", value: formatAmount(item.bordereau_vs_component_delta) },
      { label: "\u0394 agr\u00e9g\u00e9 / composant", value: formatAmount(item.aggregate_vs_component_delta) },
      { label: "\u0394 agr\u00e9g\u00e9 / individuel", value: formatAmount(item.aggregate_vs_individual_delta) },
    ];

    return '<div class="kv-grid">' + rows
      .filter(function (row) { return row.value !== NOT_AVAILABLE; })
      .map(function (row) {
        return '<div class="kv-row">'
          + '<span class="kv-row__label">' + escapeHtml(row.label) + '</span>'
          + '<span class="kv-row__value">' + escapeHtml(row.value) + '</span>'
          + '</div>';
      }).join("") + '</div>';
  }

  function renderContributionWarnings(warnings) {
    return '<div class="contrib-warning">'
      + '<span class="contrib-warning__title">Vigilance</span>'
      + '<ul class="contrib-warning__list">'
      + warnings.map(function (warning) {
        return '<li>' + escapeHtml(String(warning)) + '</li>';
      }).join("")
      + '</ul>'
      + '</div>';
  }

  // ── URSSAF details rendering (Slice D) ──────────────────────
  //
  // Slice D restructures the URSSAF detail view around CTP codes so the
  // 4 levels of the control chain (Agrégé → Bordereau → Code → Salariés)
  // are reachable without leaving the screen. The top-level table shows
  // one row per CTP (from item.urssaf_code_breakdowns). Clicking a row
  // reveals a sub-panel with:
  //   - the existing per-assiette detail rows scoped to that CTP
  //     (so rate / computed-amount controls stay visible)
  //   - an employee sub-table for "rattachable" CTPs, or an explanation
  //     for "non_rattache" / "manquant_individuel" CTPs.
  //
  // Default expansion: CTPs that carry an écart (declared-side mismatch
  // or non-zero declared/individuel delta) auto-expand on first render so
  // users see the offending rows without extra clicks. User overrides
  // persist through state.expandedUrssafCtps until scope / establishment
  // changes.

  function _displayedAmount(breakdown, value) {
    // Render helper: for reduction rows flagged by the backend
    // (display_absolute=True on 003/004/668), the UI shows the amount as a
    // positive magnitude regardless of its raw DSN sign. Backend values stay
    // signed for audit; this is purely a render concern.
    if (value == null) return value;
    if (breakdown && breakdown.display_absolute) {
      var n = typeof value === "number" ? value : parseFloat(value);
      if (!isNaN(n)) return Math.abs(n);
    }
    return value;
  }

  function _displayedDelta(breakdown) {
    // Business comparison for the collapsed row. For display_absolute rows the
    // user-facing delta is abs(declared) - abs(individual), because DSN sign
    // conventions on these reductions are asymmetric (declared positive, S81
    // individual negative), so the signed breakdown.delta is not the number
    // the payroll admin is reading on the row.
    if (breakdown == null) return null;
    if (!breakdown.display_absolute) return breakdown.delta;
    if (breakdown.declared_amount == null || breakdown.individual_amount == null) {
      return breakdown.delta;
    }
    var d = parseFloat(breakdown.declared_amount);
    var i = parseFloat(breakdown.individual_amount);
    if (isNaN(d) || isNaN(i)) return breakdown.delta;
    return Math.abs(d) - Math.abs(i);
  }

  function _ctpHasIssue(breakdown, assietteDetails) {
    // Returns true when a CTP row needs to be surfaced under the default
    // "Afficher uniquement les écarts" filter — i.e. whenever the row carries
    // ANY kind of issue the payroll user needs to see. Broader than a strict
    // declared-vs-individual écart so that explanation-carrying rows
    // (non_rattache / manquant_individuel / partial-collapse warnings) are
    // never silently hidden by the default filter.
    //
    // Criteria (any one is sufficient):
    //   1. Declared-side écart: any assiette row with rate_mismatch or
    //      amount_mismatch.
    //   2. Individual-side écart: non-zero breakdown.delta that is NOT
    //      within the euro tolerance (backend-supplied delta_within_unit).
    //   3. Mapping status is anything other than "rattachable" — so
    //      non_rattache and manquant_individuel rows are always visible and
    //      the UI can explicitly explain why the drill-down is unavailable.
    //   4. Breakdown carries at least one warning (e.g. the Slice C partial
    //      multi-assiette collapse warning) — the user must see the row to
    //      read the warning.
    for (var i = 0; i < assietteDetails.length; i++) {
      var d = assietteDetails[i];
      if (d.rate_mismatch || d.amount_mismatch) return true;
    }
    if (breakdown && breakdown.delta != null) {
      var dv = parseFloat(breakdown.delta);
      if (!isNaN(dv) && dv !== 0 && !breakdown.delta_within_unit) return true;
    }
    if (breakdown && breakdown.mapping_status && breakdown.mapping_status !== "rattachable") {
      return true;
    }
    if (breakdown && Array.isArray(breakdown.warnings) && breakdown.warnings.length > 0) {
      return true;
    }
    return false;
  }

  function _urssafCtpExpandKey(item, ctpCode) {
    return getItemStableKey(item) + ":ctp:" + (ctpCode || "");
  }

  function _isUrssafCtpExpanded(item, ctpCode, hasIssueDefault) {
    var key = _urssafCtpExpandKey(item, ctpCode);
    if (state.expandedUrssafCtps.hasOwnProperty(key)) {
      return state.expandedUrssafCtps[key];
    }
    return !!hasIssueDefault;
  }

  function _renderUrssafAssietteSubRows(assietteDetails) {
    // Per-assiette sub-table (the previous 6-col format, scoped to one CTP,
    // minus the Code / Libellé columns which are redundant at this level).
    if (!assietteDetails || assietteDetails.length === 0) {
      return '<div class="urssaf-ctp-empty-message">Aucune variante d\u2019assiette pour ce code.</div>';
    }
    var headerHtml = '<thead><tr>'
      + '<th>Assiette</th><th>Taux</th><th>Montant</th><th>Delta</th>'
      + '</tr></thead>';
    var rowsHtml = assietteDetails.map(function (detail) {
      var rowCls = 'detail-row detail-row--' + (detail.status || 'ok');

      var assietteLabel = detail.assiette_label || detail.assiette_qualifier || '';
      var assietteTitle = assietteLabel ? ' title="' + escapeHtml(assietteLabel) + '"' : '';
      var assietteHtml = escapeHtml(formatAmount(detail.base_amount))
        + (assietteLabel ? '<span class="cell-sublabel">' + escapeHtml(assietteLabel) + '</span>' : '');

      var tauxHtml, tauxTitle = '';
      if (detail.rate_mismatch && detail.rate != null && detail.expected_rate != null) {
        tauxHtml = '<span class="cell-mismatch">'
          + escapeHtml(formatRate(detail.rate))
          + ' <span class="cell-arrow">\u2192</span> '
          + escapeHtml(formatRate(detail.expected_rate))
          + '</span>';
        tauxTitle = ' title="Taux DSN\u00a0: ' + escapeHtml(formatRate(detail.rate))
          + ' | Taux r\u00e9f\u00e9rence\u00a0: ' + escapeHtml(formatRate(detail.expected_rate)) + '"';
      } else {
        tauxHtml = escapeHtml(formatRate(detail.rate));
      }

      var montantHtml, montantTitle = '';
      if (detail.amount_mismatch && detail.declared_amount != null && detail.computed_amount != null) {
        montantHtml = '<span class="cell-mismatch">'
          + escapeHtml(formatAmount(detail.declared_amount))
          + ' <span class="cell-arrow">\u2192</span> '
          + escapeHtml(formatAmount(detail.computed_amount))
          + '</span>';
        montantTitle = ' title="Montant DSN\u00a0: ' + escapeHtml(formatAmount(detail.declared_amount))
          + ' | Montant recalcul\u00e9\u00a0: ' + escapeHtml(formatAmount(detail.computed_amount)) + '"';
      } else if (detail.declared_amount != null) {
        montantHtml = escapeHtml(formatAmount(detail.declared_amount));
      } else if (detail.computed_amount != null) {
        montantHtml = escapeHtml(formatAmount(detail.computed_amount))
          + ' <span class="badge-recalc">Recalcul\u00e9</span>';
        montantTitle = ' title="Montant absent de la DSN, recalcul\u00e9 \u00e0 partir de l\u2019assiette et du taux"';
      } else {
        montantHtml = escapeHtml(formatAmount(null));
      }

      var deltaHtml = 'NC';
      if (detail.delta != null) {
        var dv = parseFloat(detail.delta);
        if (!isNaN(dv) && dv !== 0) {
          deltaHtml = '<span class="cell-delta">' + escapeHtml(formatAmount(detail.delta)) + '</span>';
        }
      }

      var rowHtml = '<tr class="' + rowCls + '">'
        + '<td class="mono"' + assietteTitle + '>' + assietteHtml + '</td>'
        + '<td class="mono"' + tauxTitle + '>' + tauxHtml + '</td>'
        + '<td class="mono"' + montantTitle + '>' + montantHtml + '</td>'
        + '<td class="mono">' + deltaHtml + '</td>'
        + '</tr>';

      if (detail.warnings && detail.warnings.length > 0) {
        rowHtml += '<tr class="detail-warning-row">'
          + '<td colspan="4">'
          + detail.warnings.map(function (w) {
              return '<div class="inline-warning">'
                + '<span class="inline-warning__icon">&#9888;</span>'
                + '<span class="inline-warning__text">' + escapeHtml(String(w)) + '</span>'
                + '</div>';
            }).join("")
          + '</td></tr>';
      }

      return rowHtml;
    }).join("");

    return '<div class="urssaf-sub-section">'
      + '<h5 class="urssaf-sub-section__title">D\u00e9tail par assiette</h5>'
      + '<table class="data-table urssaf-sub-table">'
      + headerHtml
      + '<tbody>' + rowsHtml + '</tbody>'
      + '</table>'
      + '</div>';
  }

  function _renderUrssafEmployeesSubSection(breakdown) {
    // Show salariés for rattachable CTPs; explain the reason otherwise.
    var status = breakdown.mapping_status || 'non_rattache';

    if (status === 'non_rattache') {
      var reason = breakdown.mapping_reason || 'no_verified_mapping_rule';
      var reasonText;
      if (reason === 'rule_not_enabled') {
        reasonText = '<strong>R\u00e8gle en attente de validation.</strong> '
          + 'Une r\u00e8gle de rattachement existe pour ce CTP mais n\u2019est pas encore '
          + 'valid\u00e9e pour un usage en production.';
      } else if (reason === 'missing_runtime_condition') {
        reasonText = '<strong>Condition non remplie.</strong> '
          + 'Ce CTP est reconnu mais les conditions de rattachement ne sont pas '
          + 'r\u00e9unies dans cette DSN.';
      } else if (reason === 'unsupported_declared_qualifier') {
        reasonText = '<strong>Variante d\u2019assiette non prise en charge.</strong> '
          + 'Ce CTP est reconnu mais au moins une variante d\u2019assiette d\u00e9clar\u00e9e '
          + 'n\u2019est pas encore prise en charge.';
      } else if (reason === 'missing_declared_qualifier') {
        reasonText = '<strong>Qualifiant d\u2019assiette manquant.</strong> '
          + 'Ce CTP est reconnu mais aucun qualifiant d\u2019assiette exploitable '
          + 'n\u2019a \u00e9t\u00e9 trouv\u00e9 dans cette DSN.';
      } else {
        // no_verified_mapping_rule — e.g. CTP 430D.
        reasonText = '<strong>Mapping salari\u00e9 non encore confirm\u00e9 pour ce code.</strong> '
          + 'Le montant d\u00e9clar\u00e9 au niveau de l\u2019\u00e9tablissement est bien lu, mais '
          + 'aucun lien v\u00e9rifi\u00e9 ne relie pour l\u2019instant ce CTP \u00e0 une cotisation '
          + 'individuelle salari\u00e9 (<code>S21.G00.81</code>). '
          + 'Le d\u00e9tail par salari\u00e9 est donc volontairement masqu\u00e9 — il sera '
          + 'ajout\u00e9 lorsque la correspondance aura \u00e9t\u00e9 valid\u00e9e.';
      }
      return '<div class="urssaf-sub-section">'
        + '<h5 class="urssaf-sub-section__title">Salari\u00e9s</h5>'
        + '<div class="urssaf-ctp-empty-message urssaf-ctp-empty-message--non-rattache">'
        + reasonText
        + '</div>'
        + '</div>';
    }

    if (status === 'manquant_individuel') {
      // e.g. CTP 635D — mapping known, but the expected S81 code is absent
      // from this DSN's employee blocks. Distinct from non_rattache (430D):
      // here the link is validated, only the data is missing.
      return '<div class="urssaf-sub-section">'
        + '<h5 class="urssaf-sub-section__title">Salari\u00e9s</h5>'
        + '<div class="urssaf-ctp-empty-message urssaf-ctp-empty-message--missing">'
        + '<strong>Lignes salari\u00e9s attendues mais absentes de cette DSN.</strong> '
        + 'La correspondance entre ce CTP et une cotisation individuelle est connue '
        + '(code attendu\u00a0: <code>'
        + escapeHtml(breakdown.individual_code || '?')
        + '</code>), mais aucune ligne <code>S21.G00.81</code> correspondante n\u2019a '
        + '\u00e9t\u00e9 trouv\u00e9e chez les salari\u00e9s de cet \u00e9tablissement. '
        + 'La ventilation par salari\u00e9 n\u2019est donc pas affich\u00e9e — c\u2019est un '
        + 'manque de donn\u00e9e dans la DSN, pas une mapping manquante.'
        + '</div>'
        + '</div>';
    }

    // rattachable
    var employees = Array.isArray(breakdown.employees) ? breakdown.employees : [];
    if (employees.length === 0) {
      // Shouldn't happen when mapping_status === 'rattachable' (backend
      // guarantees at least one employee), but stay defensive.
      return '';
    }

    var rowsHtml = employees.map(function (emp) {
      var lines = Array.isArray(emp.record_lines) ? emp.record_lines : [];
      var linesLabel = lines.length === 0
        ? NOT_AVAILABLE
        : lines.slice(0, 5).map(function (l) { return 'L' + l; }).join(', ')
          + (lines.length > 5 ? ' \u2026' : '');
      var linesTitle = lines.length > 0
        ? ' title="Lignes DSN\u00a0: ' + escapeHtml(lines.map(function (l) { return 'L' + l; }).join(', ')) + '"'
        : '';
      // Employees now carry the full set of contributing S81 codes; join them
      // so the drill-down shows every code that rolled into this employee's
      // total (previously we displayed a single code and duplicated the row
      // per code).
      var codesList = Array.isArray(emp.individual_codes) && emp.individual_codes.length > 0
        ? emp.individual_codes
        : (emp.individual_code ? [emp.individual_code] : []);
      var codesLabel = codesList.length > 0 ? codesList.join(', ') : NOT_AVAILABLE;
      var codesTitle = codesList.length > 1
        ? ' title="Codes S81 contribuant au total de ce salari\u00e9\u00a0: ' + escapeHtml(codesLabel) + '"'
        : '';
      return '<tr>'
        + '<td>' + escapeHtml(emp.employee_name || NOT_AVAILABLE) + '</td>'
        + '<td class="mono"' + codesTitle + '>' + escapeHtml(codesLabel) + '</td>'
        + '<td class="mono">' + escapeHtml(formatAmount(_displayedAmount(breakdown, emp.amount))) + '</td>'
        + '<td class="mono"' + linesTitle + '>' + linesLabel + '</td>'
        + '</tr>';
    }).join("");

    var appliedCodes = Array.isArray(breakdown.applied_individual_codes) && breakdown.applied_individual_codes.length > 0
      ? ' &mdash; codes S81 appliqu\u00e9s\u00a0: ' + breakdown.applied_individual_codes.map(escapeHtml).join(', ')
      : '';

    // Rattachable rows with no declared amount (typically AT-rate-only D
    // variants like 100D / 726D / 863D) are not broken — the URSSAF side just
    // doesn't expose a safely computable aggregate. Flag this explicitly so
    // the user doesn't read the absence as a bug.
    var declaredNote = '';
    if (breakdown.declared_amount == null) {
      declaredNote = '<div class="urssaf-info-note">'
        + '<strong>Montant d\u00e9clar\u00e9 URSSAF non disponible pour cette variante.</strong> '
        + 'Ce code expose ici uniquement le contexte d\u00e9claratif (assiette et taux), '
        + 'par exemple les lignes AT d\u00e9clar\u00e9es par taux seul. '
        + 'Le d\u00e9tail salari\u00e9 ci-dessous reste fiable ; aucun montant agr\u00e9g\u00e9 n\u2019a '
        + '\u00e9t\u00e9 reconstitu\u00e9 pour \u00e9viter toute valeur fantaisiste.'
        + '</div>';
    }

    return '<div class="urssaf-sub-section">'
      + '<h5 class="urssaf-sub-section__title">Salari\u00e9s (' + employees.length + ')' + appliedCodes + '</h5>'
      + declaredNote
      + '<table class="data-table urssaf-sub-table urssaf-employees-table">'
      + '<thead><tr>'
      + '<th>Salari\u00e9</th><th>Code S81</th><th>Montant</th><th>Lignes DSN</th>'
      + '</tr></thead>'
      + '<tbody>' + rowsHtml + '</tbody>'
      + '</table>'
      + '</div>';
  }

  function _renderUrssafCtpRattachementBadge(breakdown) {
    var status = breakdown.mapping_status || 'non_rattache';
    if (status === 'rattachable') {
      var hasDelta = false;
      if (breakdown.delta != null) {
        var dv = parseFloat(breakdown.delta);
        hasDelta = !isNaN(dv) && dv !== 0 && !breakdown.delta_within_unit;
      }
      if (hasDelta) {
        return '<span class="status-badge status-badge--ecart">\u00c9cart rattachement</span>';
      }
      return '<span class="status-badge status-badge--ok">Rattach\u00e9</span>';
    }
    if (status === 'manquant_individuel') {
      return '<span class="status-badge status-badge--manquant_individuel">Manquant individuel</span>';
    }
    return '<span class="status-badge status-badge--non_rattache">Non rattach\u00e9</span>';
  }

  function renderUrssafDetailsTable(item) {
    var details = Array.isArray(item.details) ? item.details : [];
    var breakdowns = Array.isArray(item.urssaf_code_breakdowns) ? item.urssaf_code_breakdowns : [];

    // Group assiette details by mapped_code (falling back to ctp_code) so the
    // per-mapped-row backend split (e.g. 100D vs 100P) keeps its matching
    // assiette sub-rows in each expanded row — not the union of both.
    var detailsByMapped = {};
    details.forEach(function (d) {
      var key = d.mapped_code || d.ctp_code || '';
      if (!key) return;
      if (!detailsByMapped[key]) detailsByMapped[key] = [];
      detailsByMapped[key].push(d);
    });

    // Build one CTP-level row per entry in urssaf_code_breakdowns. Fall back
    // to the assiette-grouped details if the backend didn't emit any
    // breakdowns (defensive — Slice C always populates it for URSSAF items
    // that have S23 children).
    var ctpRows = breakdowns.length > 0
      ? breakdowns.map(function (b) {
          var key = b.mapped_code || b.ctp_code;
          return {
            ctp_code: b.ctp_code,
            mapped_code: key,
            label: b.ctp_label,
            breakdown: b,
            assietteDetails: detailsByMapped[key] || [],
          };
        })
      : Object.keys(detailsByMapped).map(function (key) {
          var firstDetail = detailsByMapped[key][0] || {};
          return {
            ctp_code: firstDetail.ctp_code || key,
            mapped_code: key,
            label: firstDetail.label || null,
            breakdown: null,
            assietteDetails: detailsByMapped[key],
          };
        });

    var totalCtps = ctpRows.length;
    var issueFlags = ctpRows.map(function (row) {
      return _ctpHasIssue(row.breakdown, row.assietteDetails);
    });
    var issueCount = issueFlags.filter(function (x) { return x; }).length;
    var filterActive = state.contribFilterEcartsOnly;

    var toolbar = '<div class="contrib-filter-toolbar">'
      + '<label class="contrib-filter-toggle">'
      + '<input type="checkbox" class="contrib-filter-toggle__input"'
      + ' data-action="toggle-ecarts-filter"'
      + (filterActive ? ' checked' : '') + '>'
      + '<span class="contrib-filter-toggle__label">Afficher uniquement les \u00e9carts</span>'
      + '</label>'
      + '<span class="contrib-filter-count">' + issueCount + ' \u00e9cart(s) / ' + totalCtps + ' CTP</span>'
      + '</div>';

    // Apply filter.
    var visibleRows = ctpRows.filter(function (_, idx) {
      return !filterActive || issueFlags[idx];
    });

    var emptyMsg = filterActive && totalCtps > 0
      ? 'Aucun \u00e9cart d\u00e9tect\u00e9 sur ' + totalCtps + ' CTP. D\u00e9cochez le filtre pour tout afficher.'
      : 'Aucun d\u00e9tail disponible';

    if (visibleRows.length === 0) {
      return toolbar
        + '<div class="contrib-details-wrap">'
        + '<table class="data-table urssaf-ctp-table" style="margin-top: var(--sp-4);">'
        + '<thead><tr>'
        + '<th class="urssaf-ctp-table__chevron-col"></th>'
        + '<th>Code</th><th>Libell\u00e9</th>'
        + '<th>D\u00e9clar\u00e9</th><th>Individuel</th><th>Delta code</th>'
        + '<th>Rattachement</th>'
        + '</tr></thead>'
        + '<tbody><tr><td colspan="7" class="data-table__empty">' + emptyMsg + '</td></tr></tbody>'
        + '</table>'
        + '</div>';
    }

    var bodyHtml = visibleRows.map(function (row) {
      var b = row.breakdown;
      var assietteDetails = row.assietteDetails;
      var hasIssue = _ctpHasIssue(b, assietteDetails);
      // Expand key is the mapped_code so 100D and 100P keep independent
      // expansion state.
      var expandKey = row.mapped_code || row.ctp_code;
      var expanded = _isUrssafCtpExpanded(item, expandKey, hasIssue);

      var mappedCode = row.mapped_code
        || (assietteDetails[0] && (assietteDetails[0].mapped_code || assietteDetails[0].ctp_code))
        || row.ctp_code
        || NOT_AVAILABLE;

      // Per-CTP declared / individual / delta come from the breakdown when
      // present. For display_absolute rows, helpers render positive magnitudes
      // and recompute the business delta from the abs values (so the number in
      // the "Delta code" column matches what the payroll admin is comparing).
      var declaredCell;
      if (b != null && b.declared_amount == null && b.mapping_status === 'rattachable') {
        // AT-rate-only D rows (100D / 726D / 863D …) and any other
        // single-variant row where .005 isn't declared. We intentionally do
        // not fabricate an aggregate amount here; show an explicit label so
        // the "N.C." doesn't look like a bug.
        declaredCell = '<span class="cell-info"'
          + ' title="Le montant d\u00e9clar\u00e9 URSSAF (S21.G00.23.005) n\u2019est pas disponible'
          + ' pour cette variante (par ex. lignes AT d\u00e9clar\u00e9es par taux seul).'
          + ' Le d\u00e9tail salari\u00e9 reste consultable.">Non calculable</span>';
      } else if (b != null) {
        declaredCell = escapeHtml(formatAmount(_displayedAmount(b, b.declared_amount)));
      } else {
        declaredCell = escapeHtml(formatAmount(null));
      }
      var individualCell = b != null
        ? escapeHtml(formatAmount(_displayedAmount(b, b.individual_amount)))
        : escapeHtml(formatAmount(null));
      var deltaCell = 'NC';
      if (b != null) {
        var displayedDelta = _displayedDelta(b);
        if (displayedDelta != null) {
          var dv = parseFloat(displayedDelta);
          if (!isNaN(dv) && dv !== 0 && !b.delta_within_unit) {
            deltaCell = '<span class="cell-delta">' + escapeHtml(formatAmount(displayedDelta)) + '</span>';
          } else if (!isNaN(dv)) {
            deltaCell = escapeHtml(formatAmount(displayedDelta));
          }
        }
      }

      var rattachementBadge = b != null
        ? _renderUrssafCtpRattachementBadge(b)
        : '<span class="status-badge status-badge--non_rattache">Non rattach\u00e9</span>';

      var rowCls = 'urssaf-ctp-row'
        + (expanded ? ' urssaf-ctp-row--expanded' : '')
        + (hasIssue ? ' urssaf-ctp-row--ecart' : '');

      // data-ctp-code carries the mapped_code (row-identity key), not the
      // raw CTP — the click handler uses it verbatim to build the expansion
      // state key and must line up with _urssafCtpExpandKey's argument above.
      var parentRow = '<tr class="' + rowCls + '" data-action="toggle-urssaf-ctp" data-ctp-code="' + escapeHtml(expandKey) + '">'
        + '<td class="urssaf-ctp-table__chevron-col"><span class="urssaf-ctp-chevron">\u25b6</span></td>'
        + '<td class="mono">' + escapeHtml(mappedCode) + '</td>'
        + '<td>' + escapeHtml(row.label || NOT_AVAILABLE) + '</td>'
        + '<td class="mono">' + declaredCell + '</td>'
        + '<td class="mono">' + individualCell + '</td>'
        + '<td class="mono">' + deltaCell + '</td>'
        + '<td>' + rattachementBadge + '</td>'
        + '</tr>';

      // Row-level warnings (from UrssafCodeBreakdown.warnings) surface inside
      // the parent row area so they stay visible even when collapsed.
      var breakdownWarnings = (b && Array.isArray(b.warnings)) ? b.warnings : [];
      var warningRow = '';
      if (breakdownWarnings.length > 0) {
        warningRow = '<tr class="detail-warning-row urssaf-ctp-warning-row">'
          + '<td colspan="7">'
          + breakdownWarnings.map(function (w) {
              return '<div class="inline-warning">'
                + '<span class="inline-warning__icon">&#9888;</span>'
                + '<span class="inline-warning__text">' + escapeHtml(String(w)) + '</span>'
                + '</div>';
            }).join("")
          + '</td></tr>';
      }

      // Expansion content is always rendered; visibility is controlled via
      // the ``hidden`` attribute so the click handler can toggle it via
      // direct DOM manipulation without a full re-render.
      var expansionContent = '<tr class="urssaf-ctp-expansion"' + (expanded ? '' : ' hidden') + '>'
        + '<td colspan="7">'
        + '<div class="urssaf-ctp-expansion__content">'
        + _renderUrssafAssietteSubRows(assietteDetails)
        + (b != null ? _renderUrssafEmployeesSubSection(b) : '')
        + '</div>'
        + '</td>'
        + '</tr>';

      return parentRow + warningRow + expansionContent;
    }).join("");

    // Count warnings on filtered-out rows so the user knows they exist.
    // Note: rows carrying breakdown.warnings are already visible (see
    // _ctpHasIssue rule 4), so we only need to count assiette-level warnings
    // that slipped past rate_mismatch / amount_mismatch on otherwise-OK CTPs.
    var hiddenWarningCount = 0;
    if (filterActive) {
      ctpRows.forEach(function (row, idx) {
        if (issueFlags[idx]) return;
        row.assietteDetails.forEach(function (d) {
          if (d.warnings && d.warnings.length > 0 && !d.rate_mismatch && !d.amount_mismatch) {
            hiddenWarningCount += d.warnings.length;
          }
        });
      });
    }
    var hiddenWarningNotice = hiddenWarningCount > 0
      ? '<div class="contrib-hidden-warnings">'
        + hiddenWarningCount + ' avertissement(s) sur des lignes masqu\u00e9es par le filtre'
        + '</div>'
      : '';

    return toolbar
      + '<div class="contrib-details-wrap">'
      + '<table class="data-table urssaf-ctp-table" style="margin-top: var(--sp-4);">'
      + '<thead><tr>'
      + '<th class="urssaf-ctp-table__chevron-col"></th>'
      + '<th>Code</th><th>Libell\u00e9</th>'
      + '<th>D\u00e9clar\u00e9</th><th>Individuel</th><th>Delta code</th>'
      + '<th>Rattachement</th>'
      + '</tr></thead>'
      + '<tbody>' + bodyHtml + '</tbody>'
      + '</table>'
      + '</div>'
      + hiddenWarningNotice;
  }

  function renderContributionDetailsTable(item) {
    if (item && item.family === "urssaf") {
      return renderUrssafDetailsTable(item);
    }

    var details = Array.isArray(item.details) ? item.details : [];
    var body = details.length === 0
      ? '<tr><td colspan="3" class="data-table__empty">Aucun d\u00e9tail disponible</td></tr>'
      : details.map(function (detail) {
          return '<tr>'
            + '<td>' + escapeHtml(detail.key || NOT_AVAILABLE) + '</td>'
            + '<td>' + escapeHtml(detail.label || NOT_AVAILABLE) + '</td>'
            + '<td class="mono">' + escapeHtml(formatAmount(detail.declared_amount)) + '</td>'
            + '</tr>';
        }).join("");

    return '<div class="contrib-details-wrap">'
      + '<table class="data-table contrib-details-table" style="margin-top: var(--sp-4);">'
      + '<thead><tr><th>Salari\u00e9</th><th>D\u00e9tail</th><th>Montant</th></tr></thead>'
      + '<tbody>' + body + '</tbody>'
      + '</table>'
      + '</div>';
  }

  // ── Client-side file validation ──────────────────────────

  function isDsnFile(file) {
    var name = file && file.name ? file.name.toLowerCase() : "";
    return name.endsWith(".dsn") || name.endsWith(".txt") || name.endsWith(".edi");
  }

  var errorTimer = null;

  function showDropzoneError(msg) {
    $dropzoneError.textContent = msg;
    if (errorTimer) clearTimeout(errorTimer);
    errorTimer = setTimeout(function () {
      $dropzoneError.textContent = "";
      errorTimer = null;
    }, 3000);
  }

  function clearDropzoneError() {
    if (errorTimer) {
      clearTimeout(errorTimer);
      errorTimer = null;
    }
    $dropzoneError.textContent = "";
  }

  // ── Upload ───────────────────────────────────────────────

  function handleFile(file) {
    if (!isDsnFile(file)) {
      showDropzoneError("Seuls les fichiers .dsn, .txt ou .edi sont accept\u00e9s");
      return;
    }
    clearDropzoneError();
    upload(file);
  }

  function fileToBase64(file) {
    return new Promise(function (resolve) {
      var reader = new FileReader();
      reader.onload = function () {
        resolve(reader.result.split(",")[1] || "");
      };
      reader.onerror = function () { resolve(null); };
      reader.readAsDataURL(file);
    });
  }

  async function upload(file) {
    var b64 = await fileToBase64(file);
    setState({
      phase: "uploading",
      hasUploadAttempted: true,
      lastUploadFilename: file.name || null,
      lastUploadFileBase64: b64,
    });

    var form = new FormData();
    form.append("file", file);

    try {
      var res = await fetch("/api/extract", { method: "POST", body: form });
      var json = await res.json();

      if (!res.ok) {
        setState({
          phase: "error",
          error: { detail: json.detail || "\u00c9chec du chargement", warnings: json.warnings || [] },
        });
        return;
      }

      var initialTab = getInitialContributionTab(json);
      setState({
        phase: "results",
        data: json,
        scope: "global",
        activeEstIdx: 0,
        activeContributionTab: initialTab,
        feedbackOpen: false,
        feedbackSubmitting: false,
        feedbackSuccess: false,
      });
    } catch (err) {
      setState({
        phase: "error",
        error: { detail: "Erreur r\u00e9seau\u00a0: " + err.message, warnings: [] },
      });
    }
  }

  // ── Reset ────────────────────────────────────────────────

  function reset() {
    $fileInput.value = "";
    clearDropzoneError();
    setState({
      phase: "empty",
      data: null,
      error: null,
      scope: "global",
      activeEstIdx: 0,
      activeContributionTab: "urssaf",
      activePage: "tracking",
      contribFilterEcartsOnly: true,
      expandedContribItems: {},
      expandedUrssafCtps: {},
      hasUploadAttempted: false,
      lastUploadFilename: null,
      lastUploadFileBase64: null,
      feedbackOpen: false,
      feedbackSubmitting: false,
      feedbackSuccess: false,
    });
  }

  // ── Event listeners ──────────────────────────────────────

  // Drag and drop
  var dragCounter = 0;

  $dropzone.addEventListener("dragenter", function (e) {
    e.preventDefault();
    dragCounter++;
    $dropzone.classList.add("dropzone--active");
  });

  $dropzone.addEventListener("dragover", function (e) {
    e.preventDefault();
  });

  $dropzone.addEventListener("dragleave", function (e) {
    e.preventDefault();
    dragCounter--;
    if (dragCounter <= 0) {
      dragCounter = 0;
      $dropzone.classList.remove("dropzone--active");
    }
  });

  $dropzone.addEventListener("drop", function (e) {
    e.preventDefault();
    dragCounter = 0;
    $dropzone.classList.remove("dropzone--active");
    var files = e.dataTransfer.files;
    if (files.length > 0) handleFile(files[0]);
  });

  // Browse button
  $browseBtn.addEventListener("click", function () {
    $fileInput.click();
  });

  // File input
  $fileInput.addEventListener("change", function () {
    if ($fileInput.files.length > 0) handleFile($fileInput.files[0]);
  });

  // Page navigation
  document.querySelectorAll(".page-nav__btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var page = btn.dataset.page;
      if (page && page !== state.activePage) {
        setState({ activePage: page });
      }
    });
  });

  // Scope toggle
  document.querySelectorAll(".scope-toggle__btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var newScope = btn.dataset.scope;
      if (newScope === state.scope) return;
      if (newScope === "establishment" && state.data && state.data.establishments.length === 0) return;
      setState({ scope: newScope, activeEstIdx: 0, expandedContribItems: {}, expandedUrssafCtps: {} });
    });
  });

  // Establishment tabs (event delegation)
  $establishmentTabs.addEventListener("click", function (e) {
    var btn = e.target.closest(".tab-bar__btn");
    if (!btn) return;
    var idx = parseInt(btn.dataset.index, 10);
    if (idx !== state.activeEstIdx) {
      setState({ activeEstIdx: idx, expandedContribItems: {}, expandedUrssafCtps: {} });
    }
  });

  $contribFamilyTabs.addEventListener("click", function (e) {
    var btn = e.target.closest(".tab-bar__btn");
    if (!btn) return;
    var tab = btn.dataset.tab;
    if (!tab || tab === state.activeContributionTab) return;
    setState({ activeContributionTab: tab });
  });

  $contribFamilyPanels.addEventListener("click", function (e) {
    // Slice D: URSSAF CTP-level toggle takes precedence over the card-level
    // toggle because a CTP row lives inside a .contrib-item, so both
    // e.target.closest() calls would match the same click without this guard.
    var ctpRow = e.target.closest("[data-action='toggle-urssaf-ctp']");
    if (ctpRow) {
      if (e.target.tagName === "INPUT") return; // let the filter toggle through
      var article = ctpRow.closest(".contrib-item");
      if (!article) return;
      var itemKey = article.dataset.itemId;
      var ctpCode = ctpRow.dataset.ctpCode || "";
      // Find the immediate expansion sibling row so we can toggle it.
      var expansionRow = ctpRow.nextElementSibling;
      // Skip a warning row if present (it sits between the parent row and
      // the expansion row when UrssafCodeBreakdown.warnings is non-empty).
      while (expansionRow && !expansionRow.classList.contains("urssaf-ctp-expansion")) {
        expansionRow = expansionRow.nextElementSibling;
      }
      if (!expansionRow) return;

      var isExpanded = ctpRow.classList.contains("urssaf-ctp-row--expanded");
      if (isExpanded) {
        ctpRow.classList.remove("urssaf-ctp-row--expanded");
        expansionRow.setAttribute("hidden", "");
      } else {
        ctpRow.classList.add("urssaf-ctp-row--expanded");
        expansionRow.removeAttribute("hidden");
      }

      // Persist expansion state silently (no re-render). Keyed by
      // "{itemStableKey}:ctp:{ctp_code}" — this mirrors the key built by
      // _urssafCtpExpandKey() so a follow-up re-render restores the state.
      var ctpKey = itemKey + ":ctp:" + ctpCode;
      var updatedCtps = {};
      for (var c in state.expandedUrssafCtps) {
        updatedCtps[c] = state.expandedUrssafCtps[c];
      }
      updatedCtps[ctpKey] = !isExpanded;
      state.expandedUrssafCtps = updatedCtps;
      return;
    }

    var summary = e.target.closest("[data-action='toggle-detail']");
    if (!summary) return;
    // Don't toggle when clicking on the filter checkbox
    if (e.target.tagName === "INPUT") return;
    var article = summary.closest(".contrib-item");
    if (!article) return;
    var itemId = article.dataset.itemId;
    var body = article.querySelector(".contrib-detail-body");
    if (!body) return;

    // Direct DOM toggle for performance (no full re-render)
    var isExpanded = article.classList.contains("contrib-item--expanded");
    if (isExpanded) {
      article.classList.remove("contrib-item--expanded");
      body.classList.add("contrib-detail-body--collapsed");
    } else {
      article.classList.add("contrib-item--expanded");
      body.classList.remove("contrib-detail-body--collapsed");
    }

    // Persist in state silently (no re-render)
    var updated = {};
    for (var k in state.expandedContribItems) {
      updated[k] = state.expandedContribItems[k];
    }
    updated[itemId] = !isExpanded;
    state.expandedContribItems = updated;
  });

  $contribFamilyPanels.addEventListener("change", function (e) {
    if (e.target && e.target.dataset && e.target.dataset.action === "toggle-ecarts-filter") {
      setState({ contribFilterEcartsOnly: e.target.checked });
    }
  });

  // Reset buttons
  document.querySelectorAll('[data-action="reset"]').forEach(function (btn) {
    btn.addEventListener("click", reset);
  });

  $feedbackButtons.forEach(function (btn) {
    btn.addEventListener("click", openFeedbackModal);
  });

  $feedbackForm.addEventListener("submit", submitFeedback);

  $feedbackClose.addEventListener("click", closeFeedbackModal);
  $feedbackCancel.addEventListener("click", closeFeedbackModal);
  $feedbackDone.addEventListener("click", closeFeedbackModal);

  $feedbackModal.addEventListener("click", function (e) {
    if (e.target === $feedbackModal && !state.feedbackSubmitting) {
      closeFeedbackModal();
    }
  });

  $feedbackModal.addEventListener("cancel", function (e) {
    if (state.feedbackSubmitting) {
      e.preventDefault();
      return;
    }
    closeFeedbackModal();
  });

  $feedbackModal.addEventListener("close", function () {
    if (state.feedbackOpen) {
      state.feedbackOpen = false;
      state.feedbackSubmitting = false;
      state.feedbackSuccess = false;
      resetFeedbackForm();
    }
  });

  // Also allow clicking the whole dropzone to trigger file picker
  $dropzone.addEventListener("click", function (e) {
    if (e.target === $browseBtn || e.target === $fileInput) return;
    if (state.phase === "empty") $fileInput.click();
  });

  // Theme toggle disabled — light theme only

  // Initial render
  render();

})();
