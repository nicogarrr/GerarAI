/**
 * Texto de progreso real de una generación de tesis (realqa-21): fase en curso
 * con su número sobre el total previsto y los segundos que lleva el job.
 * Solo usa lo que devuelve /api/thesis/jobs/{id}: nunca inventa un ETA ni un
 * porcentaje que el servidor no ha medido.
 */
const PHASE_LABELS: Record<string, string> = {
    refresh_sec: 'Actualizando financieros SEC',
    collect_evidence: 'Recopilando evidencia (SEC, noticias, filings)',
    build_fundamental_model: 'Construyendo modelo fundamental',
    run_valuation: 'Ejecutando valoración determinista',
    persist_valuation_snapshot: 'Guardando valoración y snapshot',
    source_audit: 'Auditoría de fuentes y claims',
    compose_thesis: 'Redactando la tesis',
    persist_thesis: 'Persistiendo la versión',
};

export interface ThesisProgressInput {
    status: string;
    phases: Array<{ name: string; status: string }>;
    current_phase?: string | null;
    total_phases?: number | null;
    started_at?: string | null;
}

/** null = sin fase en curso (en cola, reintentando…): el llamador pone su texto. */
export function thesisProgressText(job: ThesisProgressInput | null | undefined, nowMs: number): string | null {
    if (!job || job.status !== 'running' || !job.current_phase) return null;
    const label = PHASE_LABELS[job.current_phase] ?? 'Análisis en curso';
    const index = job.phases.findIndex((phase) => phase.name === job.current_phase);
    const position = index >= 0 ? index + 1 : job.phases.length;
    const total = job.total_phases && job.total_phases >= position ? job.total_phases : null;
    const step = total ? `Fase ${position} de ${total}: ` : `Fase ${position}: `;
    const started = job.started_at ? Date.parse(job.started_at) : Number.NaN;
    const elapsed = nowMs > 0 && Number.isFinite(started) && nowMs >= started ? Math.round((nowMs - started) / 1000) : null;
    return `${step}${label}${elapsed !== null ? ` · ${elapsed} s` : ''}`;
}
