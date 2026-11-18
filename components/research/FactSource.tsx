import { isUnofficialSource } from '@/lib/research/source-quality';
import type { ResearchFact } from '@/lib/actions/research.actions';
import { formatGeneratedDate } from '@/lib/format';
import { sourceDisplay } from '@/lib/research/source-display';
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
    // El id interno del backend (YAHOO_FUNDAMENTALS, sec...) nunca se pinta
    // en crudo: etiqueta conocida o humanizado, vía sourceDisplay. #5748 retiró
    // la etiqueta visible de proveedor, así que el nombre legible queda como
    // tooltip diagnóstico sin romper esa decisión de presentación.
    const provider = fact.source_type?.trim() ? sourceDisplay(fact.source_type.trim(), locale) : null;
    const title = fact.source_title?.trim();
    const href = factSourceUrl(fact.source_url);
    // created_at is ingestion time. Never substitute it for publication time.
    const published = formatGeneratedDate(fact.source_published_at, undefined, locale);
    return (
        <div className="mt-2 space-y-1 text-left text-xs leading-5 text-gray-400 [overflow-wrap:anywhere]" title={provider ?? undefined}>
            {isUnofficialSource(fact.source_type) ? <p>{t('research.facts.unofficial')}</p> : null}
            {href ? (
                <a href={href} target="_blank" rel="noopener noreferrer" className="block text-teal-300 underline underline-offset-2 hover:text-teal-200">
                    {title || t('research.facts.sourceTitle')}
                </a>
            ) : title ? <p>{title}</p> : null}
            <p>{published ? t('research.facts.publishedDate', { date: published }) : t('research.facts.publicationUnavailable')}</p>
        </div>
    );
}
