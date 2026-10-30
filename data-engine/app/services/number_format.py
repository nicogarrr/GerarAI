"""Cifras visibles para el usuario en español (es-ES).

Réplica backend de ``formatCompact`` de ``lib/format.ts``: millones como
"M" y miles de millones como "mil M", con coma decimal y punto de miles.
Estos textos se persisten en claims y resúmenes de alertas: deben nacer ya
legibles, no depender de que cada consumidor formatee.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

NumericLike = int | float | Decimal | str | None


def _to_decimal(value: NumericLike) -> Decimal | None:
    if value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite():
        return None
    return parsed


def format_number_es(value: NumericLike, maximum_fraction_digits: int = 2) -> str | None:
    """Número con separadores es-ES (1.234,56). None si no es numérico."""
    parsed = _to_decimal(value)
    if parsed is None:
        return None
    text = f"{parsed:,.{maximum_fraction_digits}f}"
    # en-US (coma de miles, punto decimal) -> es-ES (punto de miles, coma).
    text = text.replace(",", "@").replace(".", ",").replace("@", ".")
    if "," in text:
        text = text.rstrip("0").rstrip(",")
    # Un negativo que redondea a cero es cero: «-0» no existe en es-ES
    # (ECMA-402 lo pinta sin signo con signDisplay «auto» tras redondear).
    if text.startswith("-") and not any(ch in "123456789" for ch in text):
        text = text[1:]
    return text


def format_compact_es(value: NumericLike, maximum_fraction_digits: int = 2) -> str | None:
    """Cifra compacta es-ES: 200966000000 -> "200,97 mil M"; 24000000 -> "24 M".

    La escala se fija siempre (M / mil M) porque Intl es-ES con notation
    "compact" es inconsistente para miles de millones. None si no es numérico.
    """
    parsed = _to_decimal(value)
    if parsed is None:
        return None
    # La escala se elige con la cifra YA redondeada (como hace ECMA-402 con
    # notation «compact»): 999.999.999 redondea a 1.000 M y debe salir
    # «1 mil M», no «1.000 M».
    quantum = Decimal(1).scaleb(-maximum_fraction_digits)
    abs_value = abs(parsed)
    if abs_value >= Decimal("1e9") or (abs_value / Decimal("1e6")).quantize(quantum) >= 1000:
        scaled = format_number_es(parsed / Decimal("1e9"), maximum_fraction_digits)
        return f"{scaled} mil M"
    if abs_value >= Decimal("1e6") or abs_value.quantize(quantum) >= Decimal("1e6"):
        scaled = format_number_es(parsed / Decimal("1e6"), maximum_fraction_digits)
        return f"{scaled} M"
    return format_number_es(parsed, maximum_fraction_digits)


def format_percent_es(ratio: NumericLike, fraction_digits: int = 2) -> str | None:
    """Porcentaje es-ES a partir de un ratio: -0.006 -> «-0,60 %».

    A diferencia de ``format_number_es`` conserva los decimales pedidos
    (cero final incluido): en un porcentaje «-0,60 %» y «-0,6 %» no dicen la
    misma precisión. None si no es numérico.
    """
    parsed = _to_decimal(ratio)
    if parsed is None:
        return None
    text = f"{parsed * 100:.{fraction_digits}f}".replace(".", ",")
    if text.startswith("-") and not any(ch in "123456789" for ch in text):
        text = text[1:]
    return f"{text} %"
