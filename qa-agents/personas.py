"""Personas de QA exploratoria: un objetivo realista y libertad para explorar."""
from __future__ import annotations

from dataclasses import dataclass

COMMON = """
Eres un probador de QA que se comporta como un USUARIO REAL de GerarAI, una app española de
inversión (cartera, watchlist, fichas de empresas, fiscalidad IRPF/Modelo 720, señales DCA y
un chat llamado Cerebro). La app ya está abierta en {base} y ya has iniciado sesión.
Reglas:
- Usa solo la interfaz (enlaces, botones, formularios). No inventes URLs salvo las que se te den.
- Si algo tarda, espera unos segundos una vez y sigue; no te quedes atascado en la misma acción.
- Fíjate en todo lo que esté roto o sea raro para un usuario: textos "NaN", "undefined", "null",
  "[object Object]"; importes absurdos (p. ej. 100 veces mayores de lo esperado, peniques como libras);
  porcentajes imposibles; fechas futuras o inválidas; botones que no hacen nada; páginas en blanco;
  callejones sin salida; mensajes de error; texto cortado o que se sale de la pantalla;
  cifras que no cuadran entre dos pantallas.
- Al terminar llama a done y en el texto escribe una lista, una línea por problema, con el formato:
  PROBLEMA | página (ruta) | qué viste exactamente | qué esperabas
  Si no encontraste nada, escribe: SIN PROBLEMAS. Añade al final una línea RESUMEN con lo que hiciste.
"""


@dataclass(frozen=True)
class Persona:
    slug: str
    goal: str
    start_path: str = "/inicio"
    mobile: bool = False
    max_steps: int = 30
    upload_files: tuple[str, ...] = ()


PERSONAS: list[Persona] = [
    Persona(
        "watchlist-nuevo",
        "Eres un usuario nuevo. Echa un vistazo a la pantalla de inicio y luego ve a la watchlist. "
        "Añade tres valores: Apple (AAPL, EE. UU.), Shell en Londres (SHEL.L) y LVMH en París (MC.PA). "
        "Comprueba que cada uno aparece con precio y moneda razonables (SHEL.L cotiza en peniques o libras, "
        "MC.PA en euros). Ordena la lista por alguna columna, abre la ficha de uno de ellos y vuelve. "
        "Por último elimina uno de los valores.",
        start_path="/inicio",
    ),
    Persona(
        "inversor-ibkr",
        "Eres un inversor con cuenta en Interactive Brokers. Ve a Cartera e importa tus operaciones con el "
        "botón de importar de IBKR usando el fichero CSV que tienes disponible (ibkr_activity.csv). "
        "Después revisa las posiciones, la asignación (allocation) y el tearsheet/rendimiento. "
        "Comprueba que los pesos suman ~100 %, que no hay importes absurdos y que las posiciones vendidas "
        "cuadran (vendiste 4 de 10 AAPL).",
        start_path="/portfolio",
        upload_files=("ibkr_activity.csv",),
        max_steps=35,
    ),
    Persona(
        "contribuyente-irpf",
        "Eres un contribuyente español. Ve a la sección de impuestos/fiscalidad. Genera el informe de IRPF "
        "del último año disponible y revisa ganancias y pérdidas, dividendos y retenciones. Después busca "
        "la parte del Modelo 720 (bienes en el extranjero) y comprueba qué dice. Si la cartera está vacía, "
        "comprueba que la app lo explica bien y te dice qué hacer.",
        start_path="/taxes",
    ),
    Persona(
        "dca-ficha",
        "Eres un inversor que compra periódicamente (DCA). Abre la ficha de Microsoft (MSFT) y la de Apple "
        "(AAPL) desde el buscador o la sección de research. Revisa el gráfico cambiando de rango, los niveles "
        "DCA y sus insignias (badges), la tesis y el diario de decisiones. Comprueba que los niveles tienen "
        "sentido (cada nivel más bajo que el anterior) y que las fechas no están en el futuro.",
        start_path="/research",
    ),
    Persona(
        "cerebro-chat",
        "Eres un usuario del chat Cerebro. Abre el chat (búscalo en la navegación o en /research/assistant) y "
        "haz tres preguntas, esperando cada respuesta: 1) «¿Qué diría Numantia de mi cartera?» "
        "2) «¿Cuál es el estado de los datos de AAPL?» 3) «Compara MSFT con AAPL en márgenes y dime cuál "
        "está más barata». Valora si las respuestas tienen sentido, citan fuentes y no muestran errores.",
        start_path="/research/assistant",
        max_steps=25,
    ),
    Persona(
        "movil-375",
        "Usas la app en un móvil de 375 px de ancho. Recorre inicio, watchlist, cartera, research e impuestos "
        "con la navegación inferior o el menú. Fíjate en texto cortado, elementos que se salen de la pantalla, "
        "botones demasiado pequeños o tapados y menús que no se cierran.",
        start_path="/inicio",
        mobile=True,
    ),
    Persona(
        "caos",
        "Eres un usuario caótico. Durante la sesión: pulsa atrás y adelante a menudo, haz doble clic en botones "
        "de guardar o enviar, envía formularios vacíos, escribe un texto muy largo (más de 500 caracteres "
        "seguidos, p. ej. repite 'AAAA') en buscadores y campos, mete tickers inexistentes como 'ZZZZ9' y "
        "'<script>', y abre rutas inexistentes como {base}/research/NOEXISTE y {base}/no-existe. "
        "Recorre watchlist, alertas, ajustes, research y cartera. Busca errores, pantallas en blanco y "
        "estados de los que no se puede salir.",
        start_path="/watchlist",
    ),
]


def task_for(p: Persona, base: str) -> str:
    start = f"\nEmpiezas en la página {p.start_path} (ya abierta). La navegación principal de la app está en la cabecera o en el menú; la raíz {base}/ es la portada pública, no la uses.\n"
    return COMMON.format(base=base) + start + "\nTu objetivo:\n" + p.goal.format(base=base)
