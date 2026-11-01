/**
 * Equipo de expertos en el chat (backend detrás de EXPERT_TEAM_ENABLED, apagado
 * por defecto): qué expertos respondieron. Solo cuando el motor dice que la
 * respuesta es del equipo (`model: "expert_team"`); cualquier otra respuesta
 * —o una forma inesperada— no muestra nada.
 */

export const EXPERT_NAMES = ['fundamental', 'valuation', 'risk', 'news', 'tax'] as const;
export type ExpertName = (typeof EXPERT_NAMES)[number];

export function expertTeamFromResponse(response: { model?: string | null; llm_trace?: unknown }): ExpertName[] | null {
    if (response.model !== 'expert_team') return null;
    const trace = response.llm_trace as { expert_team?: { plan?: unknown } } | null | undefined;
    const plan = trace?.expert_team?.plan;
    if (!Array.isArray(plan)) return null;
    const experts = plan.filter((name): name is ExpertName => (EXPERT_NAMES as readonly string[]).includes(String(name)));
    return experts.length ? [...new Set(experts)] : null;
}
