import type { ResearchFact } from '@/lib/actions/research.actions';
import { formatGeneratedDate } from '@/lib/format';
import type { Locale } from '@/lib/i18n/locale';
import { createTranslator } from '@/lib/i18n/translate';

/** Source metadata is evidence, not proof of independent corroboration. */
export function factSourceUrl(value: string | null | undefined): string | null {
    if (!value) return null;
    try {
        const url = new URL(value);
        return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null;
    } catch {
        return null;
    }
}

export function FactSource({ fact, locale }: { fact: ResearchFact; locale: Locale }) {
    const t = createTranslator(locale);
    const provider = fact.source_type?.trim() || t('research.facts.sourceUnavailable');
    const title = fact.source_title?.trim();
    const href = factSourceUrl(fact.source_url);
    // created_at is ingestion time. Never substitute it for publication time.
    const published = formatGeneratedDate(fact.source_published_at, undefined, locale);
    return (
        <div className="mt-2 space-y-1 text-left text-xs leading-5 text-gray-400 [overflow-wrap:anywhere]">
            <p>{t('research.facts.sourceProvider', { provider })}</p>
            {href ? (
                <a href={href} target="_blank" rel="noopener noreferrer" className="block text-teal-300 underline underline-offset-2 hover:text-teal-200">
                    {title || t('research.facts.sourceTitle')}
                </a>
            ) : title ? <p>{title}</p> : null}
            <p>{published ? t('research.facts.publishedDate', { date: published }) : t('research.facts.publicationUnavailable')}</p>
        </div>
    );
}
