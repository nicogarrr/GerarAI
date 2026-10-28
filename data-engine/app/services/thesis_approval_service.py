"""Aprobación de tesis por Telegram (human-in-the-loop mínimo viable).

Enfoque elegido: **poller ligero getUpdates** (no botones URL).

- Al generarse una tesis, si ``TELEGRAM_APPROVAL_ENABLED=true``, se envía un
  ``sendMessage`` en texto plano (sin ``parse_mode``) con ``inline_keyboard``:
  ``✅ Publicar`` / ``✏️ Revisar``. El ``callback_data`` es
  ``thesis:approve:<thesis_id>`` / ``thesis:reject:<thesis_id>``.
- Un poller ligero (``poll_telegram_approvals_once`` + script
  ``scripts/telegram_approval_poll.py``) llama a ``getUpdates`` con offset
  persistido en fichero, procesa los callbacks y actualiza el estado de la
  tesis. Todo es best-effort y nunca rompe la generación: apagado por
  defecto.
- Estado visible: campo ``ThesisVersion.status`` (``published`` /
  ``changes_requested``) + sección ``ThesisSection(section_key="approval")``,
  legible por el endpoint existente
  ``GET /api/memory/thesis/{ticker}/sections`` sin añadir rutas ni tocar
  ``openapi.json`` ni auth.

Sin red en tests: todo el parseo/transiciones es puro o usa ``httpx.Client``
inyectable vía monkeypatch (mismo patrón que ``test_telegram_notifications``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import redact_secrets
from app.core.tenancy import tenant_filters
from app.models import ThesisSection, ThesisVersion

APPROVAL_SECTION_KEY = "approval"
APPROVAL_SECTION_TITLE = "Aprobación Telegram"
APPROVAL_SECTION_ORDER = 900

CALLBACK_PREFIX = "thesis"
DECISION_APPROVE = "approve"
DECISION_REJECT = "reject"
DECISIONS = (DECISION_APPROVE, DECISION_REJECT)

# Límite de texto plano de sendMessage en Telegram.
TELEGRAM_TEXT_LIMIT = 4096

STATUS_PUBLISHED = "published"
STATUS_CHANGES_REQUESTED = "changes_requested"
SECTION_PENDING = "pending"


def build_approval_text(
    ticker: str, version: int, status: str, summary: str | None = None
) -> str:
    """Texto plano (sin parse_mode) del mensaje de aprobación."""
    lines = [
        f"Nueva tesis {ticker.upper()} v{version} pendiente de aprobación",
        f"Estado actual: {status}",
    ]
    if summary:
        lines += ["", summary.strip()]
    lines += ["", "Elige: Publicar o Revisar con los botones."]
    return "\n".join(lines)[: TELEGRAM_TEXT_LIMIT - 6]


def build_approval_keyboard(thesis_id: int) -> dict:
    """Teclado inline con callback_data (lo consume el poller getUpdates)."""
    return {
        "inline_keyboard": [
            [
                {
                    "text": "✅ Publicar",
                    "callback_data": f"{CALLBACK_PREFIX}:{DECISION_APPROVE}:{thesis_id}",
                },
                {
                    "text": "✏️ Revisar",
                    "callback_data": f"{CALLBACK_PREFIX}:{DECISION_REJECT}:{thesis_id}",
                },
            ]
        ]
    }


def build_approval_payload(thesis_id: int, text: str, chat_id: str) -> dict:
    """Cuerpo del POST sendMessage. Nunca incluye parse_mode ni el token."""
    return {
        "chat_id": chat_id,
        "text": text,
        "reply_markup": build_approval_keyboard(thesis_id),
    }


def parse_approval_callback(data: object) -> dict | None:
    """Parsea ``thesis:<approve|reject>:<thesis_id>``. None si inválido.

    Estricto a propósito: cualquier desviación (prefijo, decisión, id no
    entero positivo, partes extra, espacios) se rechaza para que el poller
    ignore callbacks ajenos o manipulados.
    """
    if not isinstance(data, str):
        return None
    parts = data.strip().split(":")
    if len(parts) != 3:
        return None
    prefix, decision, raw_id = parts
    if prefix != CALLBACK_PREFIX or decision not in DECISIONS:
        return None
    if not raw_id.isdigit():
        return None
    thesis_id = int(raw_id)
    if thesis_id <= 0:
        return None
    return {"decision": decision, "thesis_id": thesis_id}


def iter_callback_decisions(payload: object) -> list[dict]:
    """Extrae decisiones (update_id, decision, thesis_id, callback_query_id).

    Función pura sobre el JSON de getUpdates: ignora updates sin
    callback_query o con callback_data inválido.
    """
    if not isinstance(payload, dict):
        return []
    results = payload.get("result")
    if not isinstance(results, list):
        return []
    out: list[dict] = []
    for update in results:
        if not isinstance(update, dict):
            continue
        update_id = update.get("update_id")
        query = update.get("callback_query")
        if not isinstance(query, dict):
            continue
        parsed = parse_approval_callback(query.get("data"))
        if parsed is None or not isinstance(update_id, int):
            continue
        out.append(
            {
                "update_id": update_id,
                "callback_query_id": query.get("id"),
                "decision": parsed["decision"],
                "thesis_id": parsed["thesis_id"],
            }
        )
    return out


def upsert_approval_section(
    db: Session,
    thesis: ThesisVersion,
    state: str,
    via: str = "telegram",
    note: str = "",
) -> ThesisSection:
    """Crea/actualiza la sección visible ``approval`` de la tesis."""
    section = db.scalar(
        select(ThesisSection).where(
            ThesisSection.thesis_version_id == thesis.id,
            ThesisSection.section_key == APPROVAL_SECTION_KEY,
        )
    )
    if section is None:
        section = ThesisSection(
            thesis_version_id=thesis.id,
            company_id=thesis.company_id,
            section_key=APPROVAL_SECTION_KEY,
            title=APPROVAL_SECTION_TITLE,
            order_index=APPROVAL_SECTION_ORDER,
        )
        db.add(section)
        # Necesario para que tenant_id NOT NULL no falle en SQLite estricto
        # si el modelo lo exigiera en el futuro; hoy es nullable.
    section.status = state
    section.title = APPROVAL_SECTION_TITLE
    section.order_index = APPROVAL_SECTION_ORDER
    body = f"Aprobación vía {via}: {state}."
    if note:
        body += f" {note}"
    section.body = body[:4000]
    section.metadata_ = {
        "via": via,
        "state": state,
        "decided_at": datetime.now(UTC).isoformat(),
    }
    return section


def apply_approval_decision(
    db: Session,
    thesis_id: int,
    decision: str,
    via: str = "telegram",
    out: dict | None = None,
) -> ThesisVersion:
    """Aplica approve��'published / reject��'changes_requested. Idempotente.

    Lanza ValueError con decisi��n desconocida o tesis inexistente (el poller
    lo convierte en "skipped", la API podr��a mapearlo a 404/400).
    """
    if decision not in DECISIONS:
        raise ValueError(f"Unknown approval decision: {decision!r}")
    thesis = db.get(ThesisVersion, thesis_id)
    if thesis is None:
        raise ValueError(f"Unknown thesis id: {thesis_id}")
    if decision == DECISION_APPROVE:
        _assert_approvable(db, thesis)
        thesis.status = STATUS_PUBLISHED
        upsert_approval_section(
            db, thesis, "approved", via=via, note="Tesis publicada."
        )
    else:
        thesis.status = STATUS_CHANGES_REQUESTED
        upsert_approval_section(
            db, thesis, STATUS_CHANGES_REQUESTED, via=via, note="Pendiente de revisi��n."
        )
    db.commit()
    db.refresh(thesis)
    # La tesis publicada pasa a ser conocimiento consultable (Biblioteca/RAG);
    # rechazarla o publicar otra version retira la anterior. Nunca rompe la
    # aprobacion: el sync captura y loguea sus propios fallos.
    from app.models import Company
    from app.services.thesis_knowledge_sync import sync_thesis_knowledge

    company = db.get(Company, thesis.company_id)
    if company is not None:
        knowledge_sync = sync_thesis_knowledge(
            db, company, thesis, published=decision == DECISION_APPROVE
        )
        # La UI cuenta el indexado con lo devuelto, sin suponerlo: el sync
        # nunca rompe la aprobacion y un fallo queda como "failed".
        if out is not None:
            out["knowledge_sync"] = knowledge_sync
    return thesis


# States that can never be published: there is nothing to approve.
NON_APPROVABLE_STATUSES = frozenset({"insufficient_data", "draft_failed_audit"})
APPROVABLE_STATUSES = frozenset({"draft", "final", STATUS_CHANGES_REQUESTED, STATUS_PUBLISHED})


def _assert_approvable(db: Session, thesis: ThesisVersion) -> None:
    """Refuse to publish a thesis that says it must not be published.

    The REST route assigned ``thesis.status = payload.decision`` with no check
    at all, so a version generated as ``insufficient_data`` (or one that failed
    the source audit) could be marked approved while its own memo still read
    "NO VALUATION - insufficient data". The two write paths also used
    different vocabularies ("approved" vs "published"), so neither could
    constrain the other.
    """
    if thesis.status in NON_APPROVABLE_STATUSES:
        raise ValueError(
            f"thesis v{thesis.version} is {thesis.status}: there is nothing to publish"
        )
    from app.schemas.api import valuation_uses_inferred_inputs

    if valuation_uses_inferred_inputs(thesis.valuation_basis):
        raise ValueError(
            f"thesis v{thesis.version} usa inputs inferidos: valoración no disponible, "
            "no se puede publicar"
        )
    if thesis.status not in APPROVABLE_STATUSES:
        raise ValueError(
            f"thesis v{thesis.version} is {thesis.status!r}, which is not an approvable state"
        )
    latest = db.scalar(
        select(ThesisVersion.version)
        .where(
            ThesisVersion.company_id == thesis.company_id,
            *tenant_filters(db, ThesisVersion),
        )
        .order_by(ThesisVersion.version.desc())
        .limit(1)
    )
    if latest is not None and thesis.version != latest:
        raise ValueError(
            f"thesis v{thesis.version} is stale: v{latest} exists. "
            "Approve the current version."
        )


def send_thesis_approval_request(
    db: Session,
    thesis: ThesisVersion,
    ticker: str,
    settings=None,
) -> dict:
    """Envía el sendMessage con botones inline. No lanza por red.

    - Flag apagado → ``{"status": "skipped"}`` sin red ni escritura.
    - Sin token/chat → ``not_configured`` (igual que notification_service).
    - Éxito → marca sección ``approval=pending`` y ``delivered``.
    - Fallo red → ``failed`` (nunca rompe al llamante).
    """
    settings = settings or get_settings()
    if not getattr(settings, "telegram_approval_enabled", False):
        return {"status": "skipped", "reason": "approval_disabled"}
    token = settings.telegram_bot_token
    chat_id = settings.telegram_chat_id
    if not settings.telegram_enabled or not token or not chat_id:
        return {
            "status": "not_configured",
            "error": "Telegram approval requires TELEGRAM_ENABLED, TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID",
        }
    text = build_approval_text(
        ticker, thesis.version, thesis.status, thesis.executive_summary
    )
    endpoint = f"{settings.telegram_api_base_url.rstrip('/')}/bot{token}/sendMessage"
    try:
        with httpx.Client(timeout=settings.telegram_timeout_seconds) as client:
            response = client.post(
                endpoint, json=build_approval_payload(thesis.id, text, chat_id)
            )
            response.raise_for_status()
    except Exception as exc:
        return {"status": "failed", "error": redact_secrets(f"{type(exc).__name__}: {exc}")}
    upsert_approval_section(db, thesis, SECTION_PENDING, note="Mensaje enviado.")
    db.commit()
    return {"status": "delivered", "thesis_id": thesis.id}


def maybe_request_thesis_approval(
    db: Session, thesis: ThesisVersion, ticker: str
) -> dict | None:
    """Hook best-effort tras generar tesis. Nunca lanza."""
    try:
        settings = get_settings()
        if not getattr(settings, "telegram_approval_enabled", False):
            return None
        result = send_thesis_approval_request(db, thesis, ticker, settings)
        return result if result.get("status") == "delivered" else None
    except Exception:
        return None


def read_offset(state_path: str | Path) -> int:
    """Lee el offset persistido de getUpdates. 0 si falta o es corrupto."""
    try:
        raw = Path(state_path).read_text(encoding="utf-8").strip()
    except OSError:
        return 0
    return int(raw) if raw.isdigit() else 0


def write_offset(state_path: str | Path, offset: int) -> None:
    path = Path(state_path)
    if path.parent and str(path.parent) not in {"", "."}:
        path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(int(offset)), encoding="utf-8")


def _answer_callback(
    client: httpx.Client,
    base_url: str,
    token: str,
    callback_query_id: object,
    text: str,
) -> None:
    if not isinstance(callback_query_id, str) or not callback_query_id:
        return
    # nosemgrep: gerarai-broad-except-pass -- answerCallbackQuery de Telegram es cosmetico (quita el spinner); la decision ya se guardo
    try:
        response = client.post(
            f"{base_url}/bot{token}/answerCallbackQuery",
            json={"callback_query_id": callback_query_id, "text": text[:190]},
        )
        response.raise_for_status()
    except Exception:
        pass


def poll_telegram_approvals_once(
    db: Session,
    settings=None,
    state_path: str | Path | None = None,
) -> dict:
    """Una pasada getUpdates: procesa callbacks y persiste el offset.

    Devuelve ``{"status", "processed", "approved", "rejected", "skipped",
    "last_update_id"}``. Con flag apagado o sin credenciales no toca red.
    Los callbacks inválidos o sobre tesis inexistentes se cuentan como
    ``skipped`` sin abortar la pasada.
    """
    settings = settings or get_settings()
    if not getattr(settings, "telegram_approval_enabled", False):
        return {
            "status": "disabled",
            "processed": 0,
            "approved": 0,
            "rejected": 0,
            "skipped": 0,
            "last_update_id": None,
        }
    token = settings.telegram_bot_token
    chat_id = settings.telegram_chat_id
    if not settings.telegram_enabled or not token or not chat_id:
        return {
            "status": "not_configured",
            "processed": 0,
            "approved": 0,
            "rejected": 0,
            "skipped": 0,
            "last_update_id": None,
        }
    path = state_path or settings.telegram_approval_state_path
    offset = read_offset(path)
    base_url = settings.telegram_api_base_url.rstrip("/")
    result: dict = {
        "status": "ok",
        "processed": 0,
        "approved": 0,
        "rejected": 0,
        "skipped": 0,
        "last_update_id": None,
    }
    try:
        with httpx.Client(timeout=settings.telegram_timeout_seconds) as client:
            response = client.get(
                f"{base_url}/bot{token}/getUpdates",
                params={
                    "offset": offset,
                    "timeout": 0,
                    "allowed_updates": ["callback_query"],
                },
            )
            response.raise_for_status()
            payload = response.json()
            updates = payload.get("result") if isinstance(payload, dict) else None
            if not isinstance(updates, list):
                updates = []
            max_update_id: int | None = None
            for update in updates:
                if not isinstance(update, dict) or not isinstance(
                    update.get("update_id"), int
                ):
                    continue
                max_update_id = update["update_id"]
                query = update.get("callback_query")
                parsed = (
                    parse_approval_callback(query.get("data"))
                    if isinstance(query, dict)
                    else None
                )
                if parsed is None:
                    result["skipped"] += 1
                    continue
                try:
                    apply_approval_decision(
                        db, parsed["thesis_id"], parsed["decision"]
                    )
                except ValueError:
                    result["skipped"] += 1
                else:
                    result["processed"] += 1
                    if parsed["decision"] == DECISION_APPROVE:
                        result["approved"] += 1
                        _answer_callback(
                            client,
                            base_url,
                            token,
                            query.get("id"),
                            "Tesis publicada ✅",
                        )
                    else:
                        result["rejected"] += 1
                        _answer_callback(
                            client,
                            base_url,
                            token,
                            query.get("id"),
                            "Tesis marcada para revisar ✏️",
                        )
            if max_update_id is not None:
                write_offset(path, max_update_id + 1)
                result["last_update_id"] = max_update_id
    except Exception as exc:
        result["status"] = "failed"
        result["error"] = redact_secrets(f"{type(exc).__name__}: {exc}")
    return result
