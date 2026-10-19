"""Cerebro único de GerarAI: piezas comunes de los tres endpoints de consulta.

Comparten este servicio ``/api/chat``, ``/api/knowledge/chat`` y
``/api/research/assistant``:

- Contexto de página explícito (la pastilla "Viendo X" del cliente): el
  ticker viaja como texto y la Company se resuelve EN SERVIDOR contra el catálogo global; las consultas
  de contenido privado posteriores van acotadas por ``tenant_id``. El
  cliente nunca manda IDs de base de datos.
- Marca y voz: saludos y rutas degradadas en castellano natural, siempre
  con la marca GerarAI.
- Solo lectura: el cerebro no escribe memoria ni estado desde el chat
  (``maybe_write_from_chat`` quedó retirado del camino de consulta).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import Company
from app.services.company_resolver import resolve_company

BRAND_NAME = "GerarAI"

_GREETING_TOKEN = (
    r"hola|buenas|buenos d[ií]as|buenas tardes|buenas noches|hey|hi|hello|"
    r"qu[eé]\s+tal|c[oó]mo\s+est[aá]s|est[aá]s|gracias|muchas\s+gracias|ok|vale|"
    r"adi[oó]s|hasta\s+luego"
)
# Saludos compuestos: "hola, buenos dias", "hola que tal", "buenas!".
SMALL_TALK_RE = re.compile(
    rf"^\s*(?:[¿¡]\s*)?(?:{_GREETING_TOKEN})(?:[\s!.,¡¿?]+(?:{_GREETING_TOKEN}))*"
    r"[\s!.,¡¿?]*$",
    re.IGNORECASE,
)
# Saludo inicial seguido de una pregunta real: se retira para que el resto
# del enrutado (capacidades, cartera, empresa) vea la pregunta.
LEADING_GREETING_RE = re.compile(
    rf"^\s*(?:[¿¡]\s*)?(?:(?:{_GREETING_TOKEN})[\s!.,¡¿?]+)+",
    re.IGNORECASE,
)

_SMALL_TALK_ANSWER = (
    f"¡Hola! Soy el Cerebro de {BRAND_NAME}. Puedo responder a cualquier "
    "tema y, además, tengo acceso a tu cartera, tus tesis, tu research y tus "
    "documentos. Pregúntame lo que quieras."
)


def small_talk_answer(question: str) -> str:
    """Respuesta fija de cortesía, en castellano y con la marca GerarAI."""
    normalized = "".join(
        char for char in unicodedata.normalize("NFD", question.lower())
        if unicodedata.category(char) != "Mn"
    ).strip(" \t\n!.,¡¿?")
    if normalized in {"gracias", "muchas gracias"}:
        return "De nada."
    if normalized in {"adios", "hasta luego"}:
        return "Hasta luego."
    if normalized in {"ok", "vale"}:
        return "De acuerdo."
    return _SMALL_TALK_ANSWER


@dataclass(frozen=True)
class ResolvedPageContext:
    """Contexto de página ya resuelto en servidor.

    ``company`` es None cuando el ticker de la página no existe en el master
    global: el eco al cliente lo dice (la pastilla muestra la etiqueta,
    no una empresa inventada).
    """

    path: str
    label: str
    ticker: str | None
    company: Company | None

    def echo(self) -> dict:
        return {
            "path": self.path,
            "label": self.label,
            "ticker": self.ticker,
            "company_name": self.company.name if self.company else None,
            "company_resolved": self.company is not None,
        }


def resolve_page_context(db: Session, page) -> ResolvedPageContext | None:
    """Resuelve el contexto de página de la petición contra el master.

    ``page`` es el esquema ``ChatPageContext`` (o None). La resolución del
    ticker usa ``resolve_company`` contra el catálogo global Company. Esto
    no concede acceso a contenido privado: tesis, posiciones y memorias
    se consultan después con la sesión tenant-scoped. Un ticker inexistente
    no crea una empresa ni autoriza datos.
    """
    if page is None:
        return None
    ticker = (page.ticker or "").strip().upper() or None
    company = resolve_company(db, ticker) if ticker else None
    label = (page.label or "").strip() or (company.name if company else None) or ticker or page.path
    return ResolvedPageContext(
        path=page.path,
        label=label,
        ticker=company.ticker if company else ticker,
        company=company,
    )
