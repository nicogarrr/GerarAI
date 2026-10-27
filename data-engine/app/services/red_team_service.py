from datetime import UTC, datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import (
    CalculatedMetric,
    Company,
    RedTeamRun,
    ResearchReview,
    SourceAudit,
    ThesisVersion,
)
from app.services.claim_scope import live_claims
from app.services.moat_service import MoatService
from app.services.peer_analysis_service import PeerAnalysisService
from app.services.review_alert_service import ReviewAlertService
from app.services.review_copy import claim_status_label
from app.services.valuation_service import ValuationService

SEVERITY_PENALTY = {
    "critical": 25,
    "high": 15,
    "medium": 8,
    "low": 3,
}


def _finding_types(finding: dict) -> set[str]:
    """Tipos que cubre un hallazgo: el dominante más los fusionados.

    Los derivados por categoría (broken_assumptions, missing_risks) deben
    mirar todos los motivos fusionados, no solo ``finding["type"]``: si un
    claim stale+unsupported fusiona bajo ``unsupported_material_claim``, el
    motivo ``claim_stale`` sigue contando como supuesto roto.
    """
    types = {finding["type"]}
    trace = finding.get("trace") or {}
    merged = trace.get("merged_types") or []
    return types | set(merged)



def _valuation_not_publishable_message(missing_inputs: list) -> str:
    """Alerta de valoración no publicable: dice CONCRETAMENTE qué falta,
    en lenguaje de usuario (regla: identificadores internos en UI son bug)."""
    from app.services.memo_text_es import term_es

    missing = [term_es(key) for key in missing_inputs]
    if not missing:
        return "La valoración no se puede publicar porque faltan datos necesarios."
    return "La valoración no se puede publicar todavía: faltan " + ", ".join(missing) + "."

class RedTeamService:
    prompt_version = "red-team-v1"

    def run(
        self,
        db: Session,
        company: Company,
        thesis: ThesisVersion | None = None,
        *,
        commit: bool = True,
    ) -> RedTeamRun:
        thesis = thesis or db.scalar(
            select(ThesisVersion)
            .where(ThesisVersion.company_id == company.id)
            .order_by(desc(ThesisVersion.version))
            .limit(1)
        )
        run = RedTeamRun(
            company_id=company.id,
            thesis_version_id=thesis.id if thesis else None,
            status="running",
            prompt_version=self.prompt_version,
            trace={"started_at": datetime.now(UTC).isoformat()},
        )
        db.add(run)
        db.flush()

        claims = live_claims(db, company, thesis=thesis)
        findings: list[dict] = []
        for claim in claims:
            # Un claim, un hallazgo: si varias reglas disparan sobre la misma
            # afirmación se fusionan en un solo hallazgo, para que el cuerpo
            # de la alerta no repita el statement por cada motivo (bug visto
            # con RKLB: "revenue" y "shares_diluted" duplicados). El tipo es
            # el de mayor severidad y el rastro conserva todos los motivos.
            reasons: list[tuple[str, str, str]] = []
            if claim.materiality_score >= 7 and not claim.evidence:
                reasons.append(
                    ("high", "unsupported_material_claim", "material sin evidencia vinculada")
                )
            if claim.status in {
                "contradicted",
                "superseded",
                "stale",
                "uncertain",
            }:
                reasons.append(
                    (
                        "critical"
                        if claim.status == "contradicted"
                        and claim.materiality_score >= 8
                        else "high",
                        f"claim_{claim.status}",
                        f"clasificada como {claim_status_label(claim.status)}",
                    )
                )
            if claim.materiality_score >= 7 and not (
                claim.metadata_ or {}
            ).get("invalidation_conditions"):
                reasons.append(
                    ("medium", "missing_falsification_test", "sin condición de invalidación explícita")
                )
            if reasons:
                severity, finding_type, _ = max(
                    reasons, key=lambda item: SEVERITY_PENALTY[item[0]]
                )
                detail = "; ".join(reason for _, _, reason in reasons)
                findings.append(
                    self._finding(
                        severity,
                        finding_type,
                        f"Afirmación {detail}: {claim.statement}",
                        claim_id=claim.id,
                        merged_types=[item[1] for item in reasons] if len(reasons) > 1 else None,
                    )
                )

        latest_audit = (
            db.scalar(
                select(SourceAudit)
                .where(SourceAudit.thesis_version_id == thesis.id)
                .order_by(desc(SourceAudit.created_at))
                .limit(1)
            )
            if thesis
            else None
        )
        if latest_audit and not latest_audit.passed:
            unsupported = list(latest_audit.unsupported_claims or [])
            conflicts = list(latest_audit.data_conflicts or [])
            if unsupported or conflicts:
                findings.append(
                    self._finding(
                        "high",
                        "source_audit_failed",
                        (
                            "La auditoría de fuentes falló con puntuación de respaldo "
                            f"de afirmaciones {latest_audit.source_coverage_score}/100: "
                            f"{len(unsupported)} sin respaldo, {len(conflicts)} conflictos."
                        ),
                        source_audit_id=latest_audit.id,
                        required_fixes=latest_audit.required_fixes,
                    )
                )
            else:
                # Claims limpios (coverage 100, sin unsupported): no es un
                # "failed" sino un bloqueo aguas abajo (p.ej. valuation sin
                # inputs). Mensaje sin contradiccion.
                findings.append(
                    self._finding(
                        "medium",
                        "source_audit_blocked",
                        (
                            "Auditoría de fuentes bloqueada aguas abajo (puntuación de respaldo "
                            f"de afirmaciones {latest_audit.source_coverage_score}/100, sin "
                            "afirmaciones sin respaldo; el bloqueo puede deberse a la traza "
                            "u otros requisitos): "
                            f"{'; '.join(latest_audit.required_fixes or [])[:300]}"
                        ),
                        source_audit_id=latest_audit.id,
                        required_fixes=latest_audit.required_fixes,
                    )
                )

        valuation = ValuationService().value_company(db, company)
        if not valuation.get("publishable", False):
            findings.append(
                self._finding(
                    "high",
                    "valuation_not_publishable",
                    _valuation_not_publishable_message(valuation.get("missing_inputs") or []),
                    missing_inputs=valuation.get("missing_inputs", []),
                )
            )

        latest_metrics = self._latest_metrics(db, company.id)
        roic = next(
            (
                metric
                for name, metric in latest_metrics.items()
                if name.startswith("roic") and metric.value is not None
            ),
            None,
        )
        wacc = latest_metrics.get("wacc")
        if roic and wacc and wacc.value is not None and roic.value < wacc.value:
            findings.append(
                self._finding(
                    "high",
                    "returns_below_cost_of_capital",
                    f"ROIC {roic.value} por debajo del WACC {wacc.value}.",
                    roic_metric_id=roic.id,
                    wacc_metric_id=wacc.id,
                )
            )

        moat = MoatService().assess(db, company, persist=True, commit=False)
        if moat["status"] != "evidence_backed":
            findings.append(
                self._finding(
                    "medium",
                    "moat_unproven",
                    "Ninguna categoría de foso reúne suficiente evidencia con fuentes.",
                )
            )

        peer_analysis = PeerAnalysisService().analyze(db, company)
        for disadvantage in peer_analysis["disadvantages"][:3]:
            findings.append(
                self._finding(
                    "medium",
                    "peer_disadvantage",
                    self._peer_message(disadvantage),
                    peer_dimension=disadvantage.get("dimension"),
                    claim_id=disadvantage.get("claim_id"),
                )
            )

        findings.sort(
            key=lambda item: SEVERITY_PENALTY[item["severity"]],
            reverse=True,
        )
        score = max(
            0,
            100
            - sum(
                SEVERITY_PENALTY[finding["severity"]]
                for finding in findings
            ),
        )
        strongest = (
            findings[0]["message"]
            if findings
            else "No se identificó un caso bajista respaldado por evidencia; puede deberse a cobertura insuficiente, no a poco riesgo."
        )
        run.status = "completed"
        run.score = score
        run.strongest_bear_case = strongest
        run.findings = findings
        run.broken_assumptions = [
            finding["message"]
            for finding in findings
            if _finding_types(finding)
            & {
                "claim_contradicted",
                "claim_superseded",
                "returns_below_cost_of_capital",
            }
        ]
        run.missing_risks = [
            finding["message"]
            for finding in findings
            if _finding_types(finding)
            & {
                "unsupported_material_claim",
                "moat_unproven",
                "peer_disadvantage",
            }
        ]
        run.falsification_tests = [
            condition
            for claim in claims
            for condition in (claim.metadata_ or {}).get(
                "invalidation_conditions", []
            )
        ] or [
            "Define condiciones de invalidación explícitas y medibles para cada afirmación material de la tesis."
        ]
        run.trace = {
            **(run.trace or {}),
            "completed_at": datetime.now(UTC).isoformat(),
            "method": "deterministic_evidence_attack_v1",
            "claim_count": len(claims),
            "finding_count": len(findings),
            "valuation_status": valuation.get("status"),
            "moat_status": moat.get("status"),
            "peer_status": peer_analysis.get("status"),
        }
        if thesis:
            thesis.red_team_score = score

        if findings:
            existing = db.scalar(
                select(ResearchReview).where(
                    ResearchReview.company_id == company.id,
                    ResearchReview.review_type == "red_team",
                    ResearchReview.status.in_(["open", "in_progress"]),
                )
            )
            if existing is None:
                ReviewAlertService().create_review(
                    db,
                    review_type="red_team",
                    title=f"Hallazgos del red team sobre {company.ticker}",
                    summary=strongest,
                    company_id=company.id,
                    materiality_score=10 - min(5, score // 20),
                    impact_direction="negative",
                    metadata={"red_team_run_id": run.id},
                    # Prueba real realqa-16: añadir 12 empresas a la watchlist
                    # generaba 12 tesis automáticas y, con ellas, 12 avisos
                    # «La valoración no se puede publicar todavía…» que nadie
                    # había configurado. El red team es una revisión interna de
                    # la tesis: queda en la bandeja de revisión y en la ficha,
                    # pero no dispara un aviso. Los avisos son las reglas que el
                    # usuario crea.
                    emit=False,
                )
        if commit:
            db.commit()
            db.refresh(run)
        else:
            db.flush()
        return run

    def latest(self, db: Session, company: Company) -> RedTeamRun | None:
        return db.scalar(
            select(RedTeamRun)
            .where(RedTeamRun.company_id == company.id)
            .order_by(desc(RedTeamRun.created_at))
            .limit(1)
        )

    def _latest_metrics(
        self, db: Session, company_id: int
    ) -> dict[str, CalculatedMetric]:
        metrics = db.scalars(
            select(CalculatedMetric)
            .where(CalculatedMetric.company_id == company_id)
            .order_by(desc(CalculatedMetric.created_at))
        ).all()
        result: dict[str, CalculatedMetric] = {}
        for metric in metrics:
            result.setdefault(metric.metric, metric)
            result.setdefault(metric.definition_version.lower(), metric)
        return result

    def _finding(
        self, severity: str, finding_type: str, message: str, **trace
    ) -> dict:
        return {
            "severity": severity,
            "type": finding_type,
            "message": message,
            "trace": {key: value for key, value in trace.items() if value is not None},
        }

    def _peer_message(self, disadvantage: dict) -> str:
        if disadvantage.get("statement"):
            return disadvantage["statement"]
        return (
            f"{disadvantage.get('dimension')} por debajo de la mediana de comparables: "
            f"{disadvantage.get('target_value')} frente a "
            f"{disadvantage.get('peer_median')}."
        )
