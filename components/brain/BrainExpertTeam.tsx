'use client';

import type { ExpertName } from '@/lib/chat/expert-team';
import { useT } from '@/lib/i18n/client';

const EXPERT_KEYS = {
    fundamental: 'brain.expertTeam.experts.fundamental',
    valuation: 'brain.expertTeam.experts.valuation',
    risk: 'brain.expertTeam.experts.risk',
    news: 'brain.expertTeam.experts.news',
    tax: 'brain.expertTeam.experts.tax',
} as const;

/** Aviso de que la respuesta la dio el equipo de expertos: quién respondió y quién no llegó a tiempo. */
export function BrainExpertTeam({ experts, timedOut }: { experts?: ExpertName[] | null; timedOut?: ExpertName[] | null }) {
    const t = useT();
    if (!experts?.length) return null;
    return (
        <p data-testid="brain-expert-team" className="mt-2 text-xs text-slate-400 not-prose">
            <span className="font-semibold text-slate-300">{t('brain.expertTeam.title')}</span>
            {': '}
            {experts.map((name) => t(EXPERT_KEYS[name])).join(' · ')}
            {timedOut?.length ? (
                <span data-testid="brain-expert-team-timeout" className="block text-amber-300">
                    {t('brain.expertTeam.timedOut', { experts: timedOut.map((name) => t(EXPERT_KEYS[name])).join(' · ') })}
                </span>
            ) : null}
            <span className="block">{t('brain.expertTeam.note')}</span>
        </p>
    );
}
