"""Non-alerting, tenant-isolated official regulatory evidence for ASTS."""
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.tenancy import tenant_filters
from app.models import Company, NewsEvent


def persist_decrees(db, decrees: list[dict], fetched_at: datetime) -> int:
    tenant_id = db.info.get("tenant_id")
    if tenant_id is None:
        raise RuntimeError("SUBTEL ingestion requires tenant context")
    company = db.scalar(select(Company).where(Company.ticker == "ASTS"))
    if company is None:
        return 0
    created = 0
    for decree in decrees:
        row = db.scalar(select(NewsEvent).where(
            *tenant_filters(db, NewsEvent), NewsEvent.source == "SUBTEL (oficial)",
            NewsEvent.url == decree["pdf_url"],
        ))
        if row is not None:
            continue
        date = datetime.fromisoformat(decree["decree_date"]).replace(tzinfo=UTC)
        row = NewsEvent(
            tenant_id=tenant_id, company_id=company.id, date=date,
            title=f"SUBTEL: concesión a AST SpaceMobile Chile, decreto {decree['decree_number']}",
            source="SUBTEL (oficial)", url=decree["pdf_url"],
            summary=(f"Decreto de {decree['decree_date']}, solicitud {decree['request_number']}. "
                     "Concesión de Servicio Intermedio de Telecomunicaciones. "
                     "Fecha del evento: firma del decreto, no publicación en Diario Oficial. "
                     "No acredita inicio comercial. Texto primario disponible en el PDF oficial."),
            event_type="regulatory", materiality_score=5, impact_direction="neutral",
            affected_thesis=False, requires_update=False, affected_assumptions=[],
            processed_at=fetched_at,
            metadata_={"connector": "subtel", "source_kind": "official_regulatory_decree",
                       "regulatory_evidence": dict(decree), "fetched_at": fetched_at.isoformat(),
                       "event_date_basis": "decree_date", "no_new_alerts": True,
                       "headline_from_source": False,
                       "assessment": {"source_tier": "tier_primary", "source_trust_score": 1.0,
                                      "materiality_reasons": ["Documento regulatorio primario, no señal de inversión"],
                                      "source_policy": "SUBTEL oficial; publicación pendiente de verificar",
                                      "model_route": "deterministic_regulatory_evidence"}},
        )
        db.add(row)
        created += 1
    db.commit()
    return created
