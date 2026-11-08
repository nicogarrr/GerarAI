"""Borradores de ejemplo para el desglose por partes (SOTP editable).

Son SUPUESTOS DE USUARIO, no datos ni valoración de GerarAI. Se muestran como
borrador mientras el usuario no guarde su propio modelo para ese ticker; al
guardarlo, manda el suyo. No entran en ningún motor ni en el valor justo.
"""

from __future__ import annotations

# ASTS: copia literal de la tabla que Nico mandó el 8-nov-2026 (00:06 Madrid).
# Importes en millones de USD a 2030E; descuento al 12,5 % durante 4 años
# (1,125^4 = 1,6018); 389,1 M acciones + 12 M (Firefly) + ~44 M (convertibles y
# compensación) = 445 M diluidas, como en su total.
ASTS_NICO_2026_11_08 = {
    "currency": "USD",
    "base_year": 2026,
    "valuation_year": 2030,
    "discount_years": 4,
    "discount_rate": 0.125,
    "shares_current": 389.1,
    "dilution": [
        {"label": "Acciones entregadas a Firefly", "shares": 12},
        {"label": "Conversión de notas y compensación a empleados (≈44 M; 43,9 para cuadrar el total de 445 M)", "shares": 43.9},
    ],
    "author": "Nico",
    "source": "Supuestos de Nico (mensaje del 8-nov-2026). Borrador de ejemplo: no son datos verificados ni la valoración de GerarAI.",
    "stated_value_per_share": 155.81,
    "parts": [
        {"group": "A · Mayorista D2D", "name": "EE. UU. Comercial (AT&T / Verizon)", "revenue": 1350, "ebitda": 1188, "multiple": 18},
        {"group": "A · Mayorista D2D", "name": "Europa (JV Satellite Connect)", "revenue": 1030, "ebitda": 885, "multiple": 17},
        {"group": "A · Mayorista D2D", "name": "Japón y APAC (Rakuten + socios)", "revenue": 680, "ebitda": 578, "multiple": 16},
        {"group": "A · Mayorista D2D", "name": "Arabia Saudí, MENA y África (stc)", "revenue": 530, "ebitda": 450, "multiple": 15},
        {"group": "A · Mayorista D2D", "name": "Latinoamérica (Brasil, Chile…)", "revenue": 580, "ebitda": 487, "multiple": 14},
        {"group": "B · Defensa, cómputo y lanzamientos", "name": "AST Defense (radar, DoD, OTAN)", "revenue": 1450, "ebitda": 1232, "multiple": 24},
        {"group": "B · Defensa, cómputo y lanzamientos", "name": "Edge AI (AST5000) y hosted payloads", "revenue": 450, "ebitda": 360, "multiple": 22},
        {"group": "B · Defensa, cómputo y lanzamientos", "name": "Cohete Blacklift (ahorro de CapEx + vuelos)", "revenue": 250, "ebitda": 542, "multiple": 18,
         "note": "Ingresos 250 M$ más 350 M$ de ahorro de CapEx; 542 M$ es FCF equivalente, no EBITDA contable."},
        {"group": "C · Balance", "kind": "asset", "name": "Espectro L-Band (45 MHz) y 3.900 patentes", "value": 3500, "discounted": True},
        {"group": "C · Balance", "kind": "asset", "name": "Caja neta 2030E (tras CapEx de 100 satélites y Firefly)", "value": 1080, "discounted": True},
    ],
    "scenarios": [
        {"key": "pessimistic", "label": "Pesimista: 18 meses de retraso, 480 M acciones, ingresos −65 %",
         "revenue_factor": 0.35, "delay_years": 1.5, "shares_total": 480, "stated_value_per_share": 61.40},
        {"key": "rate_15", "label": "Tasa del 15 %", "discount_rate": 0.15, "stated_value_per_share": 142.50},
        {"key": "optimistic", "label": "Optimista: constelación militar «Blackbird» y adopción masiva",
         "stated_value_per_share": 341.50,
         "note": "El mensaje no da parámetros para este escenario: es una cifra declarada, no calculada."},
    ],
}

SOTP_EXAMPLES: dict[str, dict] = {"ASTS": ASTS_NICO_2026_11_08}
