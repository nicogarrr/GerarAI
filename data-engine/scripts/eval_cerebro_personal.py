"""Eval opcional del Cerebro con tus datos y un modelo REAL (gasta créditos).

Uso (desde data-engine/, con la clave del proveedor en el entorno):

    APP_ENV=test python scripts/eval_cerebro_personal.py --yes

Sin ``--yes`` o sin ninguna clave de LLM en el entorno no llama a nada.
Siembra la misma base que los tests (``tests/cerebro_seed.py``: tu cartera y tu
watchlist), hace las preguntas reales de la prueba del 27-oct y comprueba por
cada una: ruta personal, intención, anclaje de cifras y tickers, y latencia.
Las respuestas no ancladas no se muestran al usuario (cae a la determinista);
aquí se cuentan para medir cuánto inventa el modelo configurado.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

QUESTIONS = [
    "¿qué está barato de mi watchlist?",
    "¿qué riesgo tengo?",
    "¿cómo va mi cartera?",
    "¿dónde meto la aportación de este mes?",
    "¿cuándo se invalidan mis tesis?",
    "¿qué tengo en zona de recorte?",
    "¿qué sabes de mí?",
]
KEY_VARS = (
    "GROQ_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY", "OPENCODE_GO_API_KEY",
    "THESIS_GO_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY", "LLM_API_KEY",
)


async def _run() -> int:
    from app.services import user_context
    from app.services.chat_service import ChatService
    from tests.cerebro_seed import fake_dca_reader, seeded_session

    user_context.default_dca_reader = fake_dca_reader  # niveles DCA de prueba
    db = seeded_session()
    service = ChatService()
    ok = 0
    for question in QUESTIONS:
        start = time.perf_counter()
        resp = await service.answer(db, question, "portfolio", None)
        elapsed = time.perf_counter() - start
        trace = resp.llm_trace or {}
        grounded = trace.get("grounding") == "ok"
        ok += int(grounded)
        print(f"\n### {question}  ({elapsed:.1f} s)")
        print(f"ruta={trace.get('path')} intención={trace.get('intent')} modelo={resp.model} "
              f"anclada={grounded} motivo={trace.get('fallback_reason')}")
        if trace.get("ungrounded_numbers") or trace.get("ungrounded_tickers"):
            print(f"cifras no ancladas={trace.get('ungrounded_numbers')} tickers={trace.get('ungrounded_tickers')}")
        print(resp.answer)
    print(f"\nRespuestas del modelo ancladas: {ok}/{len(QUESTIONS)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="confirma que quieres gastar créditos del LLM")
    args = parser.parse_args()
    keys = [name for name in KEY_VARS if (os.environ.get(name) or "").strip()]
    if not args.yes or not keys:
        print("No se ejecuta: hace falta --yes y una clave de LLM en el entorno "
              f"({', '.join(KEY_VARS)}). Los tests con LLM de prueba no la necesitan.")
        return 0
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
