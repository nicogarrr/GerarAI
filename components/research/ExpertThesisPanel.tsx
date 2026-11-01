import type { ExpertThesis } from '@/lib/actions/expert-thesis.actions';
import type { TranslateFn } from '@/lib/i18n/translate';
import type { TranslationKey } from '@/lib/i18n/t';

const EXPERT_KEYS: Record<string, TranslationKey> = {
    fundamental: 'brain.expertTeam.experts.fundamental',
    valuation: 'brain.expertTeam.experts.valuation',
    risk: 'brain.expertTeam.experts.risk',
    news: 'brain.expertTeam.experts.news',
    tax: 'brain.expertTeam.experts.tax',
};

const STATUS_KEYS: Record<string, TranslationKey> = {
    timeout: 'brain.expertTeam.thesis.statusTimeout',
    no_data: 'brain.expertTeam.thesis.statusNoData',
    error: 'brain.expertTeam.thesis.statusError',
};

/** Solo http(s): un enlace de fuente nunca ejecuta nada en la página. */
function safeUrl(url: string | null | undefined): string | null {
    if (!url) return null;
    try {
        const parsed = new URL(url);
        return parsed.protocol === 'https:' || parsed.protocol === 'http:' ? parsed.href : null;
    } catch {
        return null;
    }
}

/**
 * Tesis guardada del equipo de expertos: una sección por experto con sus
 * afirmaciones (cada una con su [n]) y las fuentes numeradas, con enlace
 * cuando la fuente lo tiene (p. ej. el filing de la SEC).
 */
export function ExpertThesisPanel({
    thesis,
    t,
    formatDate,
}: {
    thesis: ExpertThesis | null;
    t: TranslateFn;
    formatDate?: (iso: string) => string;
}) {
    if (!thesis || !thesis.sections?.length) return null;
    const sources = thesis.sources ?? [];
    const known = new Set(sources.map((source) => source.n));
    const anchor = (n: number) => `expert-source-${thesis.run_id}-${n}`;
    return (
        <section data-testid="expert-thesis" aria-labelledby="expert-thesis-title" className="mt-12 border-t border-gray-800 pt-8">
            <h2 id="expert-thesis-title" className="text-2xl text-gray-50">{t('brain.expertTeam.thesis.title')}</h2>
            {thesis.finished_at && formatDate ? (
                <p className="mt-1 text-xs text-gray-500">{t('brain.expertTeam.thesis.generatedAt', { date: formatDate(thesis.finished_at) })}</p>
            ) : null}
            <p className="mt-2 text-sm leading-6 text-gray-400">{t('brain.expertTeam.thesis.note')}</p>
            <div className="mt-6 space-y-6">
                {thesis.sections.map((section) => {
                    const name = EXPERT_KEYS[section.expert] ? t(EXPERT_KEYS[section.expert]) : section.expert;
                    const claims = section.claims ?? [];
                    return (
                        <div key={section.expert} data-testid={`expert-thesis-${section.expert}`}>
                            <h3 className="text-lg font-semibold text-gray-100">{name}</h3>
                            {claims.length === 0 ? (
                                <p className="mt-1 text-sm text-gray-500">
                                    {t(STATUS_KEYS[section.status ?? ''] ?? STATUS_KEYS.error)}
                                </p>
                            ) : (
                                <>
                                    {section.summary ? <p className="mt-1 text-sm leading-6 text-gray-300">{section.summary}</p> : null}
                                    <ul className="mt-2 list-disc space-y-1 pl-5 text-sm leading-6 text-gray-200">
                                        {claims.map((claim, index) => (
                                            <li key={`${section.expert}-${index}`}>
                                                {claim.text}
                                                {(claim.refs ?? []).filter((n) => known.has(n)).map((n) => (
                                                    <a key={n} href={`#${anchor(n)}`} className="ml-1 text-teal-300 no-underline hover:underline">[{n}]</a>
                                                ))}
                                            </li>
                                        ))}
                                    </ul>
                                </>
                            )}
                        </div>
                    );
                })}
            </div>
            {thesis.conflicts?.length ? (
                <div className="mt-6 text-sm leading-6 text-gray-300">
                    <h3 className="font-semibold text-gray-100">{t('brain.expertTeam.thesis.conflicts')}</h3>
                    <ul className="list-disc pl-5">
                        {thesis.conflicts.map((conflict) => <li key={conflict}>{conflict}</li>)}
                    </ul>
                </div>
            ) : null}
            {thesis.verdict ? (
                <p className="mt-4 text-sm leading-6 text-gray-200" data-testid="expert-thesis-verdict">
                    <span className="font-semibold">{t('brain.expertTeam.thesis.verdict')}</span>
                    {`: ${thesis.verdict.label}. ${thesis.verdict.rationale ?? ''}`.trimEnd()}
                </p>
            ) : null}
            {sources.length ? (
                <div className="mt-6">
                    <h3 className="text-sm font-semibold text-gray-100">{t('brain.expertTeam.thesis.sources')}</h3>
                    <ol className="mt-2 space-y-1 text-xs leading-5 text-gray-400">
                        {sources.map((source) => {
                            const url = safeUrl(source.url);
                            return (
                                <li key={source.n} id={anchor(source.n)}>
                                    {url ? (
                                        <a href={url} target="_blank" rel="noopener noreferrer" className="text-teal-300 underline underline-offset-2">
                                            [{source.n}] {source.title}
                                        </a>
                                    ) : (
                                        <span>[{source.n}] {source.title}</span>
                                    )}
                                </li>
                            );
                        })}
                    </ol>
                </div>
            ) : null}
        </section>
    );
}
