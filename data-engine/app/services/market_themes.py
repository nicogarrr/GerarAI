"""Temas de mercado: rentabilidad YTD y 1M de cestas curadas (pesos iguales).

Fuente de precios: velas diarias de Yahoo Finance (gratuita, sin clave), las mismas
que ya sirve /api/market/candles. Los temas son cestas FIJAS curadas a mano en este
fichero: no existe una fuente gratuita fiable de pertenencia a temas. Consecuencias
declaradas: la cesta es la de hoy (sesgo de supervivencia), la media es simple (no es
un indice) y solo hay cierre diario.

Honestidad de los datos: un valor sin cierre del año anterior (YTD) o sin cierre de hace
un mes (1M) no cuenta para esa metrica; un tema solo publica una metrica si al menos el
70 % de sus valores la tiene. Nunca se rellena un hueco con un cero. Cada valor lleva ademas su razon de
estar en la cesta (REASONS), un hecho verificable sobre su negocio.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime, timedelta
from datetime import time as dtime
from zoneinfo import ZoneInfo

# (id, nombre visible en español, tickers). Orden = orden de aparicion en empates.
BASKETS: list[dict] = [
    {
        "id": "semiconductores",
        "name": "Semiconductores",
        "tickers": [
            "NVDA",
            "AMD",
            "AVGO",
            "TSM",
            "MU",
            "INTC",
            "QCOM",
            "AMAT",
            "LRCX",
            "KLAC",
            "ASML",
            "ARM",
        ],
    },
    {
        "id": "cuantica",
        "name": "Computación cuántica",
        "tickers": ["IONQ", "RGTI", "QBTS", "QUBT", "ARQQ", "IBM", "GOOGL", "HON"],
    },
    {
        "id": "ia",
        "name": "IA y aprendizaje automático",
        "tickers": [
            "MSFT",
            "GOOGL",
            "META",
            "AMZN",
            "PLTR",
            "AI",
            "PATH",
            "SOUN",
            "ORCL",
            "ADBE",
            "NOW",
            "TSLA",
        ],
    },
    {
        "id": "centros-de-datos",
        "name": "Centros de datos",
        "tickers": [
            "EQIX",
            "DLR",
            "IRM",
            "VRT",
            "SMCI",
            "DELL",
            "ANET",
            "CRWV",
            "NBIS",
            "APLD",
            "CORZ",
            "CIFR",
        ],
    },
    {
        "id": "ciberseguridad",
        "name": "Ciberseguridad",
        "tickers": ["CRWD", "PANW", "FTNT", "ZS", "S", "OKTA", "NET", "QLYS", "TENB", "RPD", "CHKP"],
    },
    {
        "id": "salud",
        "name": "Innovación en salud",
        "tickers": ["ISRG", "DXCM", "VRTX", "REGN", "MRNA", "CRSP", "NTLA", "BEAM", "TMO", "ILMN", "ALNY"],
    },
    {
        "id": "cloud-saas",
        "name": "Cloud y SaaS",
        "tickers": [
            "CRM",
            "NOW",
            "SNOW",
            "DDOG",
            "MDB",
            "WDAY",
            "TEAM",
            "HUBS",
            "SHOP",
            "ADBE",
            "TWLO",
            "ZM",
        ],
    },
    {
        "id": "robotica",
        "name": "Robótica y automatización",
        "tickers": ["ROK", "TER", "ZBRA", "CGNX", "EMR", "SYM", "ISRG", "FANUY", "ABBNY", "SERV"],
    },
    {
        "id": "infraestructuras",
        "name": "Infraestructuras",
        "tickers": ["PWR", "EME", "FIX", "VMC", "MLM", "CAT", "URI", "J", "ACM", "STRL", "MTZ", "DY"],
    },
    {
        "id": "defensa",
        "name": "Defensa y aeroespacial",
        "tickers": ["LMT", "RTX", "NOC", "GD", "LHX", "BA", "HII", "KTOS", "AVAV", "RKLB", "TDG", "HWM"],
    },
    {
        "id": "materiales",
        "name": "Materiales críticos",
        "tickers": ["MP", "FCX", "ALB", "LAC", "SQM", "UUUU", "TECK", "SCCO", "NEM", "CCJ", "USAR"],
    },
    {
        "id": "adtech",
        "name": "Publicidad digital y adtech",
        "tickers": ["TTD", "APP", "META", "GOOGL", "PUBM", "MGNI", "DV", "CRTO", "PINS", "RDDT", "ZETA"],
    },
    {
        "id": "utilities",
        "name": "Energía y utilities",
        "tickers": ["NEE", "DUK", "SO", "D", "AEP", "VST", "CEG", "NRG", "XEL", "SRE", "PCG", "EXC"],
    },
    {
        "id": "espacio",
        "name": "Espacio",
        "tickers": ["RKLB", "ASTS", "LUNR", "PL", "RDW", "SPCE", "BKSY", "VSAT", "IRDM", "GSAT", "MNTS"],
    },
    {
        "id": "drones",
        "name": "Drones",
        "tickers": ["AVAV", "KTOS", "RCAT", "UMAC", "ONDS", "ACHR", "JOBY", "DPRO", "AIRO", "PDYN"],
    },
    {
        "id": "fintech",
        "name": "Fintech",
        "tickers": ["XYZ", "PYPL", "AFRM", "SOFI", "HOOD", "COIN", "UPST", "TOST", "NU", "FOUR"],
    },
    {
        "id": "nuclear",
        "name": "Nuclear",
        "tickers": ["CEG", "VST", "OKLO", "SMR", "NNE", "LEU", "CCJ", "BWXT", "UEC", "NXE", "DNN", "GEV"],
    },
]


# Por que cada valor esta en su cesta: hechos verificables sobre su negocio, en
# espanol y cortos. Cobertura obligatoria (lo exige el test de justificacion):
# anadir un ticker sin su razon rompe los tests.
REASONS: dict[str, dict[str, str]] = {
    "semiconductores": {
        "NVDA": "GPU dominantes para entrenar IA",
        "AMD": "CPU EPYC y GPU Instinct",
        "AVGO": "Redes y ASICs a medida",
        "TSM": "Fabrica los chips de NVDA y Apple",
        "MU": "Memoria DRAM y HBM para IA",
        "INTC": "CPU x86 y fábricas propias",
        "QCOM": "SoC Snapdragon y módems 5G",
        "AMAT": "Equipos para fabricar chips",
        "LRCX": "Equipos de grabado para fabs",
        "KLAC": "Inspección y control de obleas",
        "ASML": "Único proveedor de litografía EUV",
        "ARM": "Arquitectura de casi todo móvil",
    },
    "cuantica": {
        "IONQ": "Ordenadores cuánticos de iones",
        "RGTI": "Chips cuánticos superconductores",
        "QBTS": "Recocido cuántico (annealing)",
        "QUBT": "Fotónica y computación cuántica",
        "ARQQ": "Cifrado resistente a cuántica",
        "IBM": "Linea IBM Quantum",
        "GOOGL": "Chip cuántico Willow (Alphabet)",
        "HON": "Quantinuum, su filial cuántica",
    },
    "ia": {
        "MSFT": "Copilot y Azure OpenAI",
        "GOOGL": "Gemini, DeepMind y chips TPU",
        "META": "Llama abierto e IA en sus apps",
        "AMZN": "AWS Bedrock y chips Trainium",
        "PLTR": "Plataforma de IA para empresas",
        "AI": "Software empresarial de IA (C3)",
        "PATH": "Automatización con IA (RPA)",
        "SOUN": "IA de voz para comercios",
        "ORCL": "Nube OCI para entrenar IA",
        "ADBE": "Firefly: IA generativa en diseño",
        "NOW": "IA en flujos de trabajo (Now Assist)",
        "TSLA": "Conducción autónoma y robot Optimus",
    },
    "centros-de-datos": {
        "EQIX": "REIT de centros neutros de datos",
        "DLR": "REIT de grandes centros de datos",
        "IRM": "REIT de datos y almacenaje",
        "VRT": "Refrigeración y energía para racks",
        "SMCI": "Servidores a medida para IA",
        "DELL": "Servidores y almacenamiento IA",
        "ANET": "Redes de centros de datos (Arista)",
        "CRWV": "Nube de GPU para IA (CoreWeave)",
        "NBIS": "Nube de IA (Nebius)",
        "APLD": "Construye campus de datos para IA",
        "CORZ": "Minería BTC reconvertida a IA",
        "CIFR": "Minería BTC y campus de IA",
    },
    "ciberseguridad": {
        "CRWD": "EDR en la nube (Falcon)",
        "PANW": "Cortafuegos y plataforma Cortex",
        "FTNT": "Cortafuegos FortiGate",
        "ZS": "Zero Trust en la nube",
        "S": "EDR autónomo (SentinelOne)",
        "OKTA": "Identidad y accesos (IAM)",
        "NET": "CDN y seguridad de red",
        "QLYS": "Gestion de vulnerabilidades",
        "TENB": "Escáner Nessus (Tenable)",
        "RPD": "Detección y respuesta (InsightIDR)",
        "CHKP": "Cortafuegos Check Point",
    },
    "salud": {
        "ISRG": "Robot quirúrgico da Vinci",
        "DXCM": "Monitores continuos de glucosa",
        "VRTX": "Medicamentos para fibrosis quística",
        "REGN": "Eylea y anticuerpos (Dupixent)",
        "MRNA": "Vacunas de ARNm",
        "CRSP": "Edición genética CRISPR",
        "NTLA": "CRISPR dentro del cuerpo",
        "BEAM": "Edición de bases del ADN",
        "TMO": "Instrumental y reactivos de laboratorio",
        "ILMN": "Secuenciación de ADN",
        "ALNY": "ARN de interferencia (RNAi)",
    },
    "cloud-saas": {
        "CRM": "CRM número 1 en la nube",
        "NOW": "Flujos de trabajo TI (ServiceNow)",
        "SNOW": "Almacén de datos en la nube",
        "DDOG": "Observabilidad en la nube",
        "MDB": "Base de datos MongoDB Atlas",
        "WDAY": "RRHH y finanzas en la nube",
        "TEAM": "Jira y Confluence (Atlassian)",
        "HUBS": "Marketing y CRM para pymes",
        "SHOP": "Comercio electronico (tiendas)",
        "ADBE": "Creative Cloud por suscripción",
        "TWLO": "APIs de mensajeria y voz",
        "ZM": "Videollamadas y suite Zoom",
    },
    "robotica": {
        "ROK": "Automatización industrial (Rockwell)",
        "TER": "Pruebas y cobots (Universal Robots)",
        "ZBRA": "Escáneres y robots de almacén",
        "CGNX": "Visión artificial industrial",
        "EMR": "Automatización industrial (Emerson)",
        "SYM": "Robots de almacén (cliente: Walmart)",
        "ISRG": "Cirugía robótica da Vinci",
        "FANUY": "Robots industriales (Fanuc)",
        "ABBNY": "Robótica y automatización (ABB)",
        "SERV": "Robots de reparto (Serve)",
    },
    "infraestructuras": {
        "PWR": "Ingeniería eléctrica y de redes (Quanta)",
        "EME": "Instalaciones mecánicas y electricas (EMCOR)",
        "FIX": "Instalaciones mecánicas (Comfort Systems)",
        "VMC": "Áridos y cemento (Vulcan)",
        "MLM": "Áridos (Martin Marietta)",
        "CAT": "Maquinaria de construcción",
        "URI": "Alquiler de maquinaria (United Rentals)",
        "J": "Ingeniería y consultoria (Jacobs)",
        "ACM": "Consultoria de infraestructuras (AECOM)",
        "STRL": "Construcción civil (Sterling)",
        "MTZ": "Infraestructura energetica (MasTec)",
        "DY": "Cableado de telecomunicaciones (Dycom)",
    },
    "defensa": {
        "LMT": "F-35 y misiles (Lockheed Martin)",
        "RTX": "Motores y misiles (Raytheon)",
        "NOC": "Bombardero B-21 y sistemas no tripulados",
        "GD": "Tanques y submarinos (General Dynamics)",
        "LHX": "Comunicaciones tácticas militares (L3Harris)",
        "BA": "Aviones comerciales y defensa",
        "HII": "Portaaviones y submarinos (HII)",
        "KTOS": "Drones militares y blancos aereos",
        "AVAV": "Drones tacticos (Switchblade)",
        "RKLB": "Lanzaderas y satélites (Rocket Lab)",
        "TDG": "Componentes aeronáuticos (TransDigm)",
        "HWM": "Componentes aeroespaciales (Howmet)",
    },
    "materiales": {
        "MP": "Tierras raras (Mountain Pass)",
        "FCX": "Cobre (Freeport-McMoRan)",
        "ALB": "Litio (Albemarle)",
        "LAC": "Litio (Thacker Pass)",
        "SQM": "Litio y yodo (Chile)",
        "UUUU": "Uranio y tierras raras (Energy Fuels)",
        "TECK": "Cobre y zinc (Teck)",
        "SCCO": "Cobre (Southern Copper)",
        "NEM": "Oro (Newmont)",
        "CCJ": "Uranio (Cameco)",
        "USAR": "Imanes de tierras raras (USA Rare Earth)",
    },
    "adtech": {
        "TTD": "Compra programatica (The Trade Desk)",
        "APP": "Monetización de apps (AppLovin)",
        "META": "Publicidad en Instagram y Facebook",
        "GOOGL": "Publicidad en búsqueda y YouTube",
        "PUBM": "Sell-side para publishers",
        "MGNI": "Sell-side (Magnite)",
        "DV": "Verificación publicitaria (DoubleVerify)",
        "CRTO": "Retargeting (Criteo)",
        "PINS": "Publicidad en Pinterest",
        "RDDT": "Publicidad en Reddit",
        "ZETA": "Marketing con IA (Zeta)",
    },
    "utilities": {
        "NEE": "Renovables y Florida Power & Light",
        "DUK": "Eléctrica regulada (Duke, Carolinas)",
        "SO": "Eléctrica regulada (Southern, Georgia)",
        "D": "Eléctrica regulada (Dominion)",
        "AEP": "Red y generación (Ohio-Texas)",
        "VST": "Generación y nuclear (Vistra)",
        "CEG": "Nuclear (Constellation)",
        "NRG": "Generación y retail (Texas)",
        "XEL": "Eléctrica regulada (Xcel)",
        "SRE": "Gas y electricidad (Sempra)",
        "PCG": "Eléctrica de California (PG&E)",
        "EXC": "Redes reguladas (Exelon)",
    },
    "espacio": {
        "RKLB": "Cohetes Electron y Neutron",
        "ASTS": "Banda ancha directa al móvil",
        "LUNR": "Modulos lunares (Intuitive Machines)",
        "PL": "Imágenes diarias de la Tierra (Planet)",
        "RDW": "Satélites y componentes (Redwire)",
        "SPCE": "Vuelos suborbitales (Virgin Galactic)",
        "BKSY": "Imágenes de alta resolución (BlackSky)",
        "VSAT": "Banda ancha por satélite (Viasat)",
        "IRDM": "Constelación de comunicaciones (Iridium)",
        "GSAT": "Satélite para iPhone (Globalstar)",
        "MNTS": "Propulsión y buses de satélite (Momentus)",
    },
    "drones": {
        "AVAV": "Switchblade y drones tacticales",
        "KTOS": "Drones de combate (XQ-58 Valkyrie)",
        "RCAT": "Drones militares (Red Cat)",
        "UMAC": "Componentes para drones (Unusual Machines)",
        "ONDS": "Redes y drones (Ondas)",
        "ACHR": "Taxi aéreo eléctrico (eVTOL Midnight)",
        "JOBY": "Taxi aéreo eléctrico (Joby)",
        "DPRO": "Drones comerciales (Draganfly)",
        "AIRO": "Drones militares y aviónica (AIRO)",
        "PDYN": "Software de control de drones (Palladyne)",
    },
    "fintech": {
        "XYZ": "Block: Cash App y Square",
        "PYPL": "Pagos en linea (PayPal)",
        "AFRM": "Compra ahora, paga después (Affirm)",
        "SOFI": "Banco digital (SoFi)",
        "HOOD": "Broker sin comisiones (Robinhood)",
        "COIN": "Exchange de cripto (Coinbase)",
        "UPST": "Prestamos con IA (Upstart)",
        "TOST": "TPV y pagos para restaurantes (Toast)",
        "NU": "Neobanco latinoamericano (Nubank)",
        "FOUR": "Pagos integrados (Shift4)",
    },
    "nuclear": {
        "CEG": "Mayor operador nuclear de EE. UU.",
        "VST": "Nuclear y gas (Vistra)",
        "OKLO": "Microrreactores (Oklo)",
        "SMR": "Diseño SMR (NuScale)",
        "NNE": "Microreactor portatil (Nano Nuclear)",
        "LEU": "Enriquecimiento HALEU (Centrus)",
        "CCJ": "Uranio (Cameco)",
        "BWXT": "Combustible nuclear naval (BWX)",
        "UEC": "Minería de uranio (Uranium Energy)",
        "NXE": "Proyecto de uranio Rook I (NexGen)",
        "DNN": "Uranio en Canada (Denison)",
        "GEV": "Turbinas y SMR BWRX-300 (GE Vernova)",
    },
}


def basket_reason(basket: dict, ticker: str) -> str | None:
    """Justificacion curada del ticker en su cesta; None si el llamador usa una
    cesta propia sin razones (tests)."""
    return REASONS.get(str(basket.get("id")), {}).get(ticker)


# Cobertura minima para publicar una metrica de un tema.
MIN_COVERAGE = 0.7
# Un valor cuyo ultimo cierre va mas de 7 dias por detras de la sesion mas reciente
# (deslistado, suspendido, dato congelado) no entra en ninguna metrica.
MAX_STALE_DAYS = 7
# Giro: 1M y YTD de signo contrario y 1M de al menos 1 punto (ruido por debajo).
TURN_MIN_ABS_1M = 1.0
HOT_TOP_N = 3
CACHE_TTL_SECONDS = 3600.0
# Un resultado parcial (Yahoo limitando) se reintenta pronto en vez de durar una hora.
PARTIAL_TTL_SECONDS = 300.0
# Un calculo sin datos (Yahoo caido) se recuerda poco tiempo: sin esto cada visita
# relanzaba las ~177 descargas (hasta FETCH_DEADLINE_SECONDS) y las peticiones
# concurrentes se encolaban una tras otra en el candado de calculo.
FAILED_TTL_SECONDS = 60.0
FETCH_WORKERS = 6
FETCH_DEADLINE_SECONDS = 40.0


_NEW_YORK = ZoneInfo("America/New_York")
# Despues de las 16:15 ET el ultimo punto diario de Yahoo ya es el cierre.
_CLOSE_SETTLED = dtime(16, 15)


def last_point_is_intraday(session: date, generated_at: datetime) -> bool:
    """True si el ultimo punto de la sesion de referencia aun puede moverse (mercado en curso)."""
    now_et = generated_at.astimezone(_NEW_YORK)
    return now_et.date() == session and now_et.weekday() < 5 and now_et.time() < _CLOSE_SETTLED


def all_symbols(baskets: list[dict] | None = None) -> list[str]:
    seen: dict[str, None] = {}
    for basket in baskets if baskets is not None else BASKETS:
        for ticker in basket["tickers"]:
            seen.setdefault(ticker, None)
    return list(seen)


def _month_back(day: date) -> date:
    """Mismo dia del mes anterior; si no existe (31 -> febrero) el ultimo dia de ese mes."""
    year, month = (day.year - 1, 12) if day.month == 1 else (day.year, day.month - 1)
    first_next = date(day.year, day.month, 1)
    last_prev = first_next - timedelta(days=1)
    return date(year, month, min(day.day, last_prev.day))


def _bars(candles: dict | None) -> list[tuple[date, float]]:
    """Pares (fecha UTC, cierre) validos y ordenados; descarta cierres no finitos o <= 0."""
    if not candles or candles.get("s") != "ok":
        return []
    out: list[tuple[date, float]] = []
    for ts, close in zip(candles.get("t") or [], candles.get("c") or [], strict=False):
        try:
            value = float(close)
            when = datetime.fromtimestamp(int(ts), tz=UTC).date()
        except (TypeError, ValueError, OverflowError, OSError):
            continue
        if math.isfinite(value) and value > 0:
            out.append((when, value))
    out.sort(key=lambda pair: pair[0])
    return out


def _last_on_or_before(
    bars: list[tuple[date, float]], limit: date, floor: date | None = None
) -> float | None:
    chosen: tuple[date, float] | None = None
    for when, close in bars:
        if when <= limit:
            chosen = (when, close)
        else:
            break
    if chosen is None:
        return None
    if floor is not None and chosen[0] < floor:
        return None
    return chosen[1]


def symbol_returns(candles: dict | None, session: date) -> dict:
    """Rentabilidades de un valor frente a la sesion de referencia.

    `session` es la sesion mas reciente de TODO el universo. YTD = ultimo cierre frente al
    ultimo cierre anterior al 1 de enero de ese año. 1M = frente al ultimo cierre de hace
    un mes (hasta 7 dias antes de esa fecha; mas atras es un hueco, no un dato).
    """
    bars = _bars(candles)
    result: dict = {"last_date": None, "ytd": None, "m1": None}
    if not bars:
        return result
    last_date, last_close = bars[-1]
    result["last_date"] = last_date
    if (session - last_date).days > MAX_STALE_DAYS:
        return result
    year_start = date(session.year, 1, 1)
    base_ytd = _last_on_or_before(bars, year_start - timedelta(days=1), year_start - timedelta(days=12))
    if base_ytd is not None:
        result["ytd"] = (last_close / base_ytd - 1.0) * 100.0
    target = _month_back(session)
    base_1m = _last_on_or_before(bars, target, target - timedelta(days=MAX_STALE_DAYS))
    if base_1m is not None:
        result["m1"] = (last_close / base_1m - 1.0) * 100.0
    return result


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def compute_themes(
    candles: dict[str, dict | None],
    baskets: list[dict] | None = None,
    generated_at: datetime | None = None,
) -> dict:
    """Ranking de temas a partir de velas ya descargadas (puro: sin red ni reloj)."""
    baskets = baskets if baskets is not None else BASKETS
    last_dates = [bars[-1][0] for bars in (_bars(c) for c in candles.values()) if bars]
    universe = all_symbols(baskets)
    if not last_dates:
        return {
            "status": "sin_datos",
            "as_of": None,
            "intraday": False,
            "generated_at": (generated_at or datetime.now(UTC)).isoformat(),
            "source": "Yahoo Finance",
            "method": "media simple",
            "symbols_total": len(universe),
            "symbols_with_data": 0,
            "themes": [],
        }
    # Sesion de referencia: la mas reciente que tienen AL MENOS tres valores; asi un unico
    # valor con un dato futuro o erroneo no deja a todos los demas como "obsoletos".
    ordered = sorted(last_dates, reverse=True)
    session = ordered[min(2, len(ordered) - 1)]

    per_symbol = {sym: symbol_returns(candles.get(sym), session) for sym in universe}
    with_data = sum(1 for r in per_symbol.values() if r["ytd"] is not None or r["m1"] is not None)

    themes: list[dict] = []
    for basket in baskets:
        total = len(basket["tickers"])
        needed = max(1, math.ceil(MIN_COVERAGE * total))
        rows = []
        for ticker in basket["tickers"]:
            r = per_symbol[ticker]
            rows.append(
                {
                    "ticker": ticker,
                    "ytd": _round(r["ytd"]),
                    "m1": _round(r["m1"]),
                    "reason": basket_reason(basket, ticker),
                }
            )
        ytd_values = [per_symbol[t]["ytd"] for t in basket["tickers"] if per_symbol[t]["ytd"] is not None]
        m1_values = [per_symbol[t]["m1"] for t in basket["tickers"] if per_symbol[t]["m1"] is not None]
        ytd = _mean(ytd_values) if len(ytd_values) >= needed else None
        m1 = _mean(m1_values) if len(m1_values) >= needed else None
        rows.sort(key=lambda row: (row["ytd"] is None, -(row["ytd"] or 0.0), row["ticker"]))
        turn = None
        if ytd is not None and m1 is not None and abs(m1) >= TURN_MIN_ABS_1M:
            if ytd < 0 < m1:
                turn = "sube"
            elif m1 < 0 < ytd:
                turn = "baja"
        themes.append(
            {
                "id": basket["id"],
                "name": basket["name"],
                "n_total": total,
                "ytd": {"pct": _round(ytd), "n": len(ytd_values)},
                "m1": {"pct": _round(m1), "n": len(m1_values)},
                "rank": None,
                "rank_1m": None,
                "hot": False,
                "turn": turn,
                "constituents": rows,
            }
        )

    by_ytd = sorted(
        (t for t in themes if t["ytd"]["pct"] is not None), key=lambda t: (-t["ytd"]["pct"], t["name"])
    )
    for position, theme in enumerate(by_ytd, start=1):
        theme["rank"] = position
        theme["hot"] = position <= HOT_TOP_N
    by_m1 = sorted(
        (t for t in themes if t["m1"]["pct"] is not None), key=lambda t: (-t["m1"]["pct"], t["name"])
    )
    for position, theme in enumerate(by_m1, start=1):
        theme["rank_1m"] = position
    # Orden de salida: los rankeados por YTD primero; los sin YTD al final, en orden de cesta.
    themes.sort(key=lambda t: (t["rank"] is None, t["rank"] or 0))

    published = sum(1 for t in themes if t["ytd"]["pct"] is not None)
    return {
        "status": "ok" if published == len(themes) and with_data >= 0.9 * len(universe) else "parcial",
        "as_of": session.isoformat(),
        "intraday": last_point_is_intraday(session, generated_at or datetime.now(UTC)),
        "generated_at": (generated_at or datetime.now(UTC)).isoformat(),
        "source": "Yahoo Finance",
        "method": "media simple",
        "symbols_total": len(universe),
        "symbols_with_data": with_data,
        "themes": themes,
    }


def fetch_all(
    symbols: list[str],
    fetch_one: Callable[[str], dict | None],
    workers: int = FETCH_WORKERS,
    deadline_seconds: float = FETCH_DEADLINE_SECONDS,
) -> dict[str, dict | None]:
    """Descarga acotada: concurrencia limitada y plazo global. Un simbolo roto o lento
    queda en None (cobertura honesta), nunca tumba el resto ni cuelga la peticion."""
    out: dict[str, dict | None] = dict.fromkeys(symbols)
    pool = ThreadPoolExecutor(max_workers=max(1, workers))
    try:
        futures = {pool.submit(fetch_one, sym): sym for sym in symbols}
        try:
            for future in as_completed(futures, timeout=deadline_seconds):
                try:
                    out[futures[future]] = future.result()
                except Exception:  # noqa: BLE001 - un simbolo no tumba el tema
                    out[futures[future]] = None
        except TimeoutError:
            pass
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return out


class ThemesCache:
    """Cache de 1 h con refresco en segundo plano (stale-while-revalidate).

    Sin dato previo, la primera peticion calcula (una sola a la vez). Con dato caducado se
    sirve el anterior marcando `stale` y se refresca en un hilo. Un calculo sin ningun
    simbolo con datos NO se guarda: Yahoo caido no puede dejar un "sin datos" durante una hora.
    """

    def __init__(
        self,
        ttl: float = CACHE_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        failed_ttl: float = FAILED_TTL_SECONDS,
    ) -> None:
        self._ttl = ttl
        self._failed_ttl = failed_ttl
        self._failed: dict | None = None
        self._failed_at = 0.0
        self._clock = clock
        self._lock = threading.Lock()
        self._compute_lock = threading.Lock()
        self._value: dict | None = None
        self._at = 0.0
        self._effective_ttl = ttl
        self._refreshing = False

    def get(self, compute: Callable[[], dict]) -> dict:
        with self._lock:
            value, at = self._value, self._at
        now = self._clock()
        if value is not None and now - at < self._effective_ttl:
            return {**value, "stale": False}
        if value is not None:
            self._refresh_async(compute)
            return {**value, "stale": True}
        failed = self._recent_failure(now)
        if failed is not None:
            return failed
        with self._compute_lock:
            with self._lock:
                if self._value is not None:
                    return {**self._value, "stale": False}
            failed = self._recent_failure(self._clock())
            if failed is not None:
                return failed
            fresh = compute()
            self._store(fresh)
            return {**fresh, "stale": False}

    def _recent_failure(self, now: float) -> dict | None:
        with self._lock:
            if self._failed is not None and now - self._failed_at < self._failed_ttl:
                return {**self._failed, "stale": False}
        return None

    def _store(self, fresh: dict) -> None:
        if fresh.get("symbols_with_data", 0) <= 0:
            with self._lock:
                self._failed = fresh
                self._failed_at = self._clock()
            return
        with self._lock:
            self._value = fresh
            self._at = self._clock()
            self._effective_ttl = (
                self._ttl if fresh.get("status") == "ok" else min(self._ttl, PARTIAL_TTL_SECONDS)
            )

    def _refresh_async(self, compute: Callable[[], dict]) -> None:
        with self._lock:
            if self._refreshing:
                return
            self._refreshing = True

        def run() -> None:
            try:
                self._store(compute())
            except Exception:  # noqa: BLE001 - seguimos sirviendo el dato anterior
                pass
            finally:
                with self._lock:
                    self._refreshing = False

        threading.Thread(target=run, name="market-themes-refresh", daemon=True).start()


def with_live_intraday(payload: dict, now: datetime | None = None) -> dict:
    """Recalcula `intraday` al SERVIR: el payload cacheado puede ser de antes del cierre."""
    as_of = payload.get("as_of")
    if not as_of:
        return payload
    try:
        session = date.fromisoformat(as_of)
    except ValueError:
        return payload
    return {**payload, "intraday": last_point_is_intraday(session, now or datetime.now(UTC))}
