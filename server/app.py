"""FastAPI web API for DSN extraction."""

from __future__ import annotations

import asyncio
import base64
import html
import json
import logging
import os
import pathlib
import re
from typing import Any

from dotenv import load_dotenv

load_dotenv()

import resend

from fastapi import FastAPI, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.staticfiles import StaticFiles

from dsn_extractor.extractors import extract
from dsn_extractor.parser import parse

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
FEEDBACK_TO_EMAIL = os.getenv("FEEDBACK_TO_EMAIL", "clement.rog.ext@linc.fr")
FEEDBACK_FROM_EMAIL = os.getenv("FEEDBACK_FROM_EMAIL", "DSN Facturation <onboarding@resend.dev>")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

STATIC_DIR = pathlib.Path(__file__).resolve().parent / "static"
logger = logging.getLogger(__name__)

app = FastAPI(title="DSN Facturation")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _error(status: int, detail: str, warnings: list[str] | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"detail": detail, "warnings": warnings or []},
    )


def _safe_str(value: Any, *, limit: int = 500) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:limit]


def _safe_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _sanitize_feedback_context(context: Any) -> dict[str, Any]:
    if not isinstance(context, dict):
        return {}

    filename = _safe_str(context.get("filename"), limit=200)
    if filename:
        filename = pathlib.Path(filename).name

    phase = _safe_str(context.get("phase"), limit=32)
    if phase not in {"results", "error"}:
        phase = None

    theme = _safe_str(context.get("theme"), limit=32)
    if theme not in {"light", "dark"}:
        theme = None

    return {
        "timestamp": _safe_str(context.get("timestamp"), limit=64),
        "phase": phase,
        "filename": filename,
        "active_page": _safe_str(context.get("active_page"), limit=64),
        "scope": _safe_str(context.get("scope"), limit=64),
        # Current frontend sends active_contribution_tab (Slice A).
        # active_contribution_family is kept for backward compatibility with
        # older clients; the two fields carry different meanings (tab id vs
        # backend family) so they must stay as separate keys.
        "active_contribution_tab": _safe_str(context.get("active_contribution_tab"), limit=64),
        "active_contribution_family": _safe_str(context.get("active_contribution_family"), limit=64),
        "browser": _safe_str(context.get("browser"), limit=400),
        "language": _safe_str(context.get("language"), limit=32),
        "theme": theme,
        "error_detail": _safe_str(context.get("error_detail"), limit=600),
        "visible_warning_count": _safe_int(context.get("visible_warning_count")),
        "comparison_ok_count": _safe_int(context.get("comparison_ok_count")),
        "comparison_mismatch_count": _safe_int(context.get("comparison_mismatch_count")),
        "comparison_warning_count": _safe_int(context.get("comparison_warning_count")),
    }


def _feedback_category_label(category: str) -> str:
    return "Amélioration" if category == "improvement" else "Problème / écart"


def _build_feedback_email(
    *,
    category: str,
    message: str,
    email: str,
    phone: str,
    context: dict[str, Any],
) -> tuple[str, str, str]:
    subject = f"[DSN Facturation] {_feedback_category_label(category)} - {email}"
    safe_message = html.escape(message).replace("\n", "<br>")
    safe_context = html.escape(json.dumps(context, ensure_ascii=False, indent=2))
    html_body = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; color: #1f2937; line-height: 1.6; max-width: 760px; margin: 0 auto; padding: 24px; }}
    h1 {{ font-size: 24px; margin-bottom: 8px; }}
    .meta, .message, .context {{ border: 1px solid #e5e7eb; border-radius: 16px; padding: 16px 18px; margin-top: 20px; }}
    .meta {{ background: #f8fafc; }}
    .message {{ background: #fff; }}
    .context {{ background: #0f172a; color: #e2e8f0; }}
    .meta p {{ margin: 0 0 6px; }}
    pre {{ margin: 0; white-space: pre-wrap; word-break: break-word; font-size: 12px; }}
  </style>
</head>
<body>
  <h1>Nouveau retour beta DSN Facturation</h1>
  <p>Un testeur a envoy&eacute; un retour depuis l'application.</p>
  <div class="meta">
    <p><strong>Type :</strong> {html.escape(_feedback_category_label(category))}</p>
    <p><strong>Email :</strong> <a href="mailto:{html.escape(email)}">{html.escape(email)}</a></p>
    <p><strong>T&eacute;l&eacute;phone :</strong> {html.escape(phone)}</p>
  </div>
  <div class="message">
    <strong>Message</strong>
    <p>{safe_message}</p>
  </div>
  <div class="context">
    <strong>Contexte technique limit&eacute;</strong>
    <pre>{safe_context}</pre>
  </div>
</body>
</html>"""
    text_body = (
        "NOUVEAU RETOUR BETA DSN FACTURATION\n"
        "===================================\n\n"
        f"Type : {_feedback_category_label(category)}\n"
        f"Email : {email}\n"
        f"Téléphone : {phone}\n\n"
        "Message\n"
        "-------\n"
        f"{message}\n\n"
        "Contexte technique limité\n"
        "-------------------------\n"
        f"{json.dumps(context, ensure_ascii=False, indent=2)}\n"
    )
    return subject, html_body, text_body


def _send_feedback_email(
    *,
    category: str,
    message: str,
    email: str,
    phone: str,
    context: dict[str, Any],
    attachment: dict[str, str] | None = None,
) -> dict[str, Any]:
    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        raise RuntimeError("Le service email n'est pas configuré.")

    resend.api_key = api_key

    subject, html_body, text_body = _build_feedback_email(
        category=category,
        message=message,
        email=email,
        phone=phone,
        context=context,
    )

    payload: dict[str, Any] = {
        "from": FEEDBACK_FROM_EMAIL,
        "to": [FEEDBACK_TO_EMAIL],
        "subject": subject,
        "html": html_body,
        "text": text_body,
        "reply_to": email,
    }

    if attachment:
        payload["attachments"] = [{
            "filename": attachment["filename"],
            "content": list(base64.b64decode(attachment["content"])),
        }]

    try:
        result = resend.Emails.send(payload)
        return {"id": result.get("id") if isinstance(result, dict) else getattr(result, "id", None)}
    except Exception as exc:
        logger.warning("Resend feedback email failed: %s", exc)
        raise RuntimeError("L'envoi du retour a échoué.") from exc


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=FileResponse)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", media_type="text/html")


@app.get("/favicon.ico", response_class=FileResponse)
def favicon() -> FileResponse:
    return FileResponse(STATIC_DIR / "favicon.svg", media_type="image/svg+xml")


@app.post("/api/extract")
async def api_extract(file: UploadFile) -> JSONResponse:
    # 1. Extension check
    filename = file.filename or ""
    if not (filename.lower().endswith(".dsn") or filename.lower().endswith(".txt") or filename.lower().endswith(".edi")):
        return _error(422, "Invalid file extension: expected .dsn, .txt or .edi")

    # 2. Read bytes and enforce size limit
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        return _error(413, "File too large: maximum 10 MB")

    # 3. Decode text (try UTF-8, fall back to Latin-1)
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    # 4. Parse
    parsed = parse(text)

    if len(parsed.all_records) == 0:
        return _error(400, "File contains no valid DSN lines", parsed.warnings)

    # 5. Extract
    try:
        result = extract(parsed, source_file=filename)
    except Exception as exc:
        return _error(500, f"Extraction failed: {exc}", parsed.warnings)

    return JSONResponse(result.model_dump(mode="json"))


@app.post("/api/feedback")
async def api_feedback(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return _error(400, "Corps de requête invalide")

    category = _safe_str(body.get("category"), limit=32)
    message = _safe_str(body.get("message"), limit=4000)
    email = _safe_str(body.get("email"), limit=320)
    phone = _safe_str(body.get("phone"), limit=64)
    consent = body.get("consent")
    context = _sanitize_feedback_context(body.get("context"))
    file_base64 = body.get("file_base64")
    file_name = _safe_str(body.get("file_name"), limit=200)

    if category not in {"improvement", "issue"}:
        return _error(400, "Type de retour invalide")
    if not message or not email or not phone:
        return _error(400, "Merci de renseigner le message, l'email et le téléphone")
    if not EMAIL_RE.match(email):
        return _error(400, "Merci de renseigner un email valide")
    if consent is not True:
        return _error(400, "Le consentement est requis")

    # Sanitize attachment: only accept base64 strings up to ~14MB (10MB file)
    attachment = None
    if isinstance(file_base64, str) and file_name and len(file_base64) <= 14_000_000:
        safe_name = pathlib.Path(file_name).name
        attachment = {"filename": safe_name, "content": file_base64}

    try:
        result = await asyncio.to_thread(
            _send_feedback_email,
            category=category,
            message=message,
            email=email,
            phone=phone,
            context=context,
            attachment=attachment,
        )
    except RuntimeError as exc:
        return _error(500, str(exc))

    return JSONResponse({"status": "ok", "id": result.get("id")})


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
