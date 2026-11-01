/**
 * Equipo de expertos en el chat (backend detrás de EXPERT_TEAM_ENABLED, apagado
 * por defecto): qué expertos respondieron y cuáles no llegaron a tiempo. Solo cuando el motor dice que la
 * respuesta es del equipo (`model: "expert_team"`); cualquier otra respuesta
 * —o una forma inesperada— no muestra nada.
 */

export const EXPERT_NAMES = ['fundamental', 'valuation', 'risk', 'news', 'tax'] as const;
export type ExpertName = (typeof EXPERT_NAMES)[number];

type ExpertTrace = { expert_team?: { plan?: unknown; answered?: unknown; timed_out?: unknown } } | null | undefined;

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
