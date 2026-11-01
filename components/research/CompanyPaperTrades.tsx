import Link from 'next/link';

import { PaperThesisLine } from '@/components/proPicks/PaperProposalCard';
import { EmptyLink, EmptyState } from '@/components/ui/empty-state';
import { Panel } from '@/components/ui/panel';
import type { PaperTradeView } from '@/lib/actions/paper-trading.actions';
import { DEFAULT_LOCALE, type Locale } from '@/lib/i18n/locale';
import type { TranslationKey } from '@/lib/i18n/t';
import { createTranslator, type TranslateFn } from '@/lib/i18n/translate';

export const COMPANY_PAPER_LIMIT = 5;
const PAPER_HREF = '/propicks?tab=paper';
const STATUS_KEYS: Record<string, TranslationKey> = { pending: 'research.companyPaper.statusPending', open: 'research.companyPaper.statusOpen', closed: 'research.companyPaper.statusClosed' };

export type CompanyPaperState = { trades: PaperTradeView[]; error?: string } | null;

function amount(value: string | null | undefined, currency: string | null, locale: Locale) {
    if (value === null || value === undefined || String(value).trim() === '') return null;
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return null;
    const sign = parsed > 0 ? '+' : '';
    return `${sign}${parsed.toLocaleString(locale === 'en' ? 'en-US' : 'es-ES', { maximumFractionDigits: 2 })} ${currency ?? ''}`.trim();
}

function day(value: string | null | undefined, locale: Locale) {
    return value && Number.isFinite(Date.parse(value))
        ? new Date(value).toLocaleDateString(locale === 'en' ? 'en-US' : 'es-ES', { timeZone: 'Europe/Madrid' })
        : null;
}

function result(trade: PaperTradeView, t: TranslateFn, locale: Locale) {
    if (trade.status === 'pending') return t('research.companyPaper.pendingResult');
    const closed = trade.status === 'closed';
    const gross = amount(closed ? trade.realized_pnl : trade.unrealized_pnl, trade.currency, locale);
    const net = amount(closed ? trade.realized_pnl_net : trade.unrealized_pnl_net, trade.currency, locale);
    if (!gross) return closed ? t('research.companyPaper.resultUnavailable') : t('research.companyPaper.openResultUnavailable');
    return `${t(closed ? 'research.companyPaper.resultClosed' : 'research.companyPaper.resultOpen', { gross })}${net ? t('research.companyPaper.net', { net }) : t('research.companyPaper.netNa')}`;
}

/**
 * Operaciones simuladas del paper book para ESTA empresa, junto al diario de decisiones:
 * la hipótesis se contrasta donde vive la tesis, no en una pantalla aparte. Solo
 * lectura; el detalle completo y la calibración siguen en ProPicks.
 */
export function CompanyPaperTrades({ ticker, state, locale = DEFAULT_LOCALE }: { ticker: string; state: CompanyPaperState; locale?: Locale }) {
    const t = createTranslator(locale);
    const description = t('research.companyPaper.description');
    const title = t('research.companyPaper.title');
    if (state === null || state.error) {
        return <Panel description={description} id="paper-trading" title={title}>
            <p className="text-sm text-amber-200" role="status">
                {state?.error ?? t('research.companyPaper.loadError')} {t('research.companyPaper.notMeaningNone')}
            </p>
        </Panel>;
    }
    // Un backend anterior al filtro por ticker devuelve todo el libro: nunca se mezclan empresas.
    const trades = state.trades.filter((trade) => trade.ticker.toUpperCase() === ticker.toUpperCase());
    if (trades.length === 0) {
        return <Panel description={description} id="paper-trading" title={title}>
            <EmptyState
                action={<EmptyLink href={PAPER_HREF}>{t('research.companyPaper.goToPaper')}</EmptyLink>}
                description={t('research.companyPaper.emptyDescription')}
                title={t('research.companyPaper.emptyTitle')}
            />
        </Panel>;
    }
    const visible = trades.slice(0, COMPANY_PAPER_LIMIT);
    return <Panel description={description} id="paper-trading" title={title}>
        <ul aria-label={t('research.companyPaper.listLabel', { ticker })} className="divide-y divide-gray-800">
            {visible.map((trade) => {
                const created = day(trade.created_at, locale);
                return <li className="space-y-1 py-3 first:pt-0 last:pb-0" key={trade.id}>
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                        <p className="text-sm font-medium text-gray-100">
                            {t(trade.direction === 'short' ? 'research.companyPaper.short' : 'research.companyPaper.long')} · {t(trade.horizon === 'five_years' ? 'research.companyPaper.horizonFiveYears' : 'research.companyPaper.horizonThirtyDays')}
                        </p>
                        <p className="text-xs text-gray-400">{STATUS_KEYS[trade.status] ? t(STATUS_KEYS[trade.status]) : t('research.companyPaper.statusUnknown')}{created ? t('research.companyPaper.createdOn', { date: created }) : ''}</p>
                    </div>
                    <p className="text-sm text-gray-300">{result(trade, t, locale)}</p>
                    <PaperThesisLine trade={trade} />
                </li>;
            })}
        </ul>
        <p className="mt-4 text-xs text-gray-400">
            {trades.length > visible.length ? t('research.companyPaper.shownOf', { shown: visible.length, total: trades.length }) : ''}
            <Link className="text-teal-300 underline decoration-gray-700 underline-offset-4 hover:text-teal-200" href={PAPER_HREF}>
                {t('research.companyPaper.detailLink')}
            </Link>
        </p>
    </Panel>;
}
