'use client';

import type { ExpertName, ExpertSummary } from '@/lib/chat/expert-team';
import { useT } from '@/lib/i18n/client';

const EXPERT_KEYS = {
    fundamental: 'brain.expertTeam.experts.fundamental',
    valuation: 'brain.expertTeam.experts.valuation',
    risk: 'brain.expertTeam.experts.risk',
    news: 'brain.expertTeam.experts.news',
    tax: 'brain.expertTeam.experts.tax',
} as const;

const STANCE_KEYS = {
    positive: 'brain.expertTeam.stance.positive',
    negative: 'brain.expertTeam.stance.negative',
    neutral: 'brain.expertTeam.stance.neutral',
} as const;

const CONFIDENCE_KEYS = {
    high: 'brain.expertTeam.confidence.high',
    medium: 'brain.expertTeam.confidence.medium',
    low: 'brain.expertTeam.confidence.low',
} as const;

/**
 * Aviso de que la respuesta la dio el equipo de expertos: quién respondió,
 * un resumen compacto por experto (postura, confianza y afirmaciones con
 * fuente) y quién no llegó a tiempo.
 */
export function BrainExpertTeam({
    experts,
    timedOut,
    summary,
}: {
    experts?: ExpertName[] | null;
    timedOut?: ExpertName[] | null;
    summary?: ExpertSummary[] | null;
}) {
    const t = useT();
    if (!experts?.length) return null;
    return (
        <p data-testid="brain-expert-team" className="mt-2 text-xs text-slate-400 not-prose">
            <span className="font-semibold text-slate-300">{t('brain.expertTeam.title')}</span>
            {': '}
            {experts.map((name) => t(EXPERT_KEYS[name])).join(' · ')}
            {summary?.length ? (
                <ul data-testid="brain-expert-team-summary" className="mt-1 space-y-0.5">
                    {summary.map((row) => (
                        <li key={row.expert}>
                            <span className="text-slate-300">{t(EXPERT_KEYS[row.expert])}</span>
                            {': '}
                            {t(STANCE_KEYS[row.stance])}
                            {row.confidence ? ` · ${t(CONFIDENCE_KEYS[row.confidence])}` : null}
                            {` · ${t('brain.expertTeam.sourced', { cited: row.cited, total: row.total })}`}
                        </li>
                    ))}
                </ul>
            ) : null}
            {timedOut?.length ? (
                <span data-testid="brain-expert-team-timeout" className="block text-amber-300">
                    {t('brain.expertTeam.timedOut', { experts: timedOut.map((name) => t(EXPERT_KEYS[name])).join(' · ') })}
                </span>
            ) : null}
            <span className="block">{t('brain.expertTeam.note')}</span>
        </p>
    );
}
