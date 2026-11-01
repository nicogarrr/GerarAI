/**
 * Equipo de expertos en el chat (backend detrás de EXPERT_TEAM_ENABLED, apagado
 * por defecto): qué expertos respondieron y cuáles no llegaron a tiempo. Solo cuando el motor dice que la
 * respuesta es del equipo (`model: "expert_team"`); cualquier otra respuesta
 * —o una forma inesperada— no muestra nada.
 */

export const EXPERT_NAMES = ['fundamental', 'valuation', 'risk', 'news', 'tax'] as const;
export type ExpertName = (typeof EXPERT_NAMES)[number];

type ExpertTrace = { expert_team?: { plan?: unknown; answered?: unknown; timed_out?: unknown; experts?: unknown } } | null | undefined;

function names(value: unknown): ExpertName[] | null {
    if (!Array.isArray(value)) return null;
    const experts = value.filter((name): name is ExpertName => (EXPERT_NAMES as readonly string[]).includes(String(name)));
    return experts.length ? [...new Set(experts)] : null;
}

/** Quién respondió: la lista `answered` del motor (o, en trazas antiguas, el plan). */
export function expertTeamFromResponse(response: { model?: string | null; llm_trace?: unknown }): ExpertName[] | null {
    if (response.model !== 'expert_team') return null;
    const trace = (response.llm_trace as ExpertTrace)?.expert_team;
    if (Array.isArray(trace?.answered)) return names(trace.answered);
    return names(trace?.plan);
}

/** Expertos que no respondieron a tiempo (la respuesta usa lo que sí llegó). */
export function expertTeamTimeoutsFromResponse(response: { model?: string | null; llm_trace?: unknown }): ExpertName[] | null {
    if (response.model !== 'expert_team') return null;
    return names((response.llm_trace as ExpertTrace)?.expert_team?.timed_out);
}

export type ExpertStance = 'positive' | 'negative' | 'neutral';
export type ExpertConfidence = 'high' | 'medium' | 'low';
/** Una fila del resumen compacto: postura, afirmaciones con fuente sobre el total y confianza. */
export type ExpertSummary = { expert: ExpertName; stance: ExpertStance; cited: number; total: number; confidence: ExpertConfidence | null };

const STANCES: readonly string[] = ['positive', 'negative', 'neutral'];
const CONFIDENCES: readonly string[] = ['high', 'medium', 'low'];

function count(value: unknown): number | null {
    return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : null;
}

/**
 * Resumen compacto por experto (`llm_trace.expert_team.experts`): solo los
 * que contestaron con fuente. La confianza la calcula el motor a partir de
 * las cuentas; un valor desconocido no se pinta.
 */
export function expertTeamSummaryFromResponse(response: { model?: string | null; llm_trace?: unknown }): ExpertSummary[] | null {
    if (response.model !== 'expert_team') return null;
    const rows = (response.llm_trace as ExpertTrace)?.expert_team?.experts;
    if (!Array.isArray(rows)) return null;
    const out: ExpertSummary[] = [];
    for (const row of rows) {
        if (!row || typeof row !== 'object') continue;
        const { expert, stance, cited, dropped, confidence } = row as Record<string, unknown>;
        const name = String(expert);
        const sourced = count(cited);
        if (!(EXPERT_NAMES as readonly string[]).includes(name) || !sourced || out.some((r) => r.expert === name)) continue;
        out.push({
            expert: name as ExpertName,
            stance: STANCES.includes(String(stance)) ? (stance as ExpertStance) : 'neutral',
            cited: sourced,
            total: sourced + (count(dropped) ?? 0),
            confidence: CONFIDENCES.includes(String(confidence)) ? (confidence as ExpertConfidence) : null,
        });
    }
    return out.length ? out : null;
}
