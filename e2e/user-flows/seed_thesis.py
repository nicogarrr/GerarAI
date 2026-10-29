"""Siembra determinista para la suite e2e/user-flows (sin red ni LLM).

Crea una tesis vigente (v1 superada y v2 publicada, con modelo publicable) para el usuario del bypass
E2E, con secciones y escenarios, para que la lectura editorial y la impresión
de /research/<ticker>/tesis se prueben con contenido real. Idempotente.

Uso (desde data-engine/, con el DATABASE_URL del backend E2E):
    python ../e2e/user-flows/seed_thesis.py MSFT
"""

from __future__ import annotations

import sys
from decimal import Decimal

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import Company, FundamentalModelVersion, Tenant, ThesisVersion

TENANT = "e2e-browser-user"

MARKDOWN = """## Resumen

Microsoft combina una franquicia de software con márgenes altos y una nube
(Azure) que crece por encima del mercado. La tesis depende de que Azure
mantenga crecimientos superiores al 20 % y de que la inversión en centros de
datos se rentabilice.

## Catalizadores

- Resultados trimestrales de Azure.
- Monetización de Copilot en Microsoft 365.

## Riesgos

- Capex por encima de lo previsto sin retorno visible.
- Regulación de competencia en la UE.
"""


def main(ticker: str) -> None:
    db = SessionLocal()
    try:
        tenant = db.scalar(select(Tenant).where(Tenant.external_id == TENANT))
        if tenant is None:
            tenant = Tenant(external_id=TENANT, name=TENANT)
            db.add(tenant)
            db.flush()
        db.info["tenant_id"] = tenant.id
        db.info["user_id"] = TENANT
        company = db.scalar(select(Company).where(Company.ticker == ticker))
        if company is None:
            raise SystemExit(f"{ticker} no existe todavía: visita su ficha antes de sembrar")
        existing = db.scalars(
            select(ThesisVersion).where(ThesisVersion.company_id == company.id)
        ).all()
        if existing:
            print(f"ya sembrada: {len(existing)} versiones")
            return
        # La puerta de publicación (backend y vista) solo deja leer la tesis
        # publicada si el último modelo fundamental es publicable: se siembra
        # uno mínimo y verificable para que se pruebe la lectura editorial y
        # no el texto archivado.
        db.add(
            FundamentalModelVersion(
                company_id=company.id,
                version=1,
                engine_version="e2e",
                algorithm_version="e2e",
                framework_key="e2e",
                horizon_years=5,
                status="published",
                publishable=True,
                input_fingerprint="e2e-input",
                forecast_fingerprint="e2e-forecast",
                market_snapshot_fingerprint="e2e-market",
                valuation_snapshot_fingerprint="e2e-valuation",
            )
        )
        for version, status in ((1, "superseded"), (2, "published")):
            db.add(
                ThesisVersion(
                    company_id=company.id,
                    version=version,
                    status=status,
                    thesis_markdown=MARKDOWN,
                    executive_summary=(
                        "Franquicia de software con nube en crecimiento; la tesis "
                        "vive o muere con Azure por encima del 20 %."
                    ),
                    rating="buy" if version == 2 else "watch",
                    hypothesis=(
                        "Azure mantiene crecimientos superiores al 20 % y la inversión "
                        "en centros de datos se rentabiliza en tres años."
                    ),
                    narrative_sections=[
                        {"titulo": "Catalizadores", "parrafos": [
                            "Resultados trimestrales de Azure.",
                            "Monetización de Copilot en Microsoft 365.",
                        ]},
                        {"titulo": "Riesgos", "parrafos": [
                            "Capex por encima de lo previsto sin retorno visible.",
                            "Regulación de competencia en la UE.",
                        ]},
                    ],
                    current_price=Decimal("336.56"),
                    bear_value=Decimal("280"),
                    base_value=Decimal("420"),
                    bull_value=Decimal("520"),
                    expected_value=Decimal("410"),
                    margin_of_safety=Decimal("0.18"),
                    data_confidence_score=70,
                    source_coverage_score=60,
                    red_team_score=55,
                    valuation_risk_score=40,
                )
            )
        db.commit()
        print("sembrada")
    finally:
        db.close()


if __name__ == "__main__":
    main(sys.argv[1].upper() if len(sys.argv) > 1 else "MSFT")
