import type { PaperTradeView } from '@/lib/actions/paper-trading.actions';
import { formatNumber } from '@/lib/format';
import { DEFAULT_LOCALE, type Locale } from '@/lib/i18n/locale';
import type { TranslationKey } from '@/lib/i18n/t';
import { createTranslator, type TranslateFn } from '@/lib/i18n/translate';

const stateLabel: Record<string, TranslationKey> = { pending: 'propicks.paper.stPending', open: 'propicks.paper.stOpen', closed: 'propicks.paper.stClosed' };
const closeLabel: Record<string, TranslationKey> = { stop: 'propicks.paper.closeStop', target: 'propicks.paper.closeTarget', horizon: 'propicks.paper.closeHorizon', manual: 'propicks.paper.closeManual' };
const warningLabel: Record<string, TranslationKey> = {
    split_cerrado_sin_ajustar: 'propicks.paper.warnSplitClosed',
    split_pendiente_sin_ajustar: 'propicks.paper.warnSplitPending',
};
const tag = (locale: Locale) => (locale === 'en' ? 'en-US' : 'es-ES');

/** Formato de cifras y fechas de la tarjeta según el idioma elegido (Ajustes → Idioma). */
function formatters(locale: Locale) {
    const t = createTranslator(locale);
    const number = (value: string | number | null | undefined) => {
        if (value === null || value === undefined || String(value).trim() === '') return t('propicks.paper.noData');
        const parsed = Number(value);
        return Number.isFinite(parsed) ? parsed.toLocaleString(tag(locale), { maximumFractionDigits: 6 }) : t('propicks.paper.noData');
    };
    const date = (value: string | null | undefined) => {
        if (!value || !Number.isFinite(Date.parse(value))) return t('propicks.paper.noData');
        return new Date(value).toLocaleString(tag(locale), { timeZone: 'Europe/Madrid' });
    };
    const conviction = (value: string) => {
        const parsed = Number(value);
        if (!value.trim() || !Number.isFinite(parsed) || parsed < 0 || parsed > 1) return t('propicks.paper.noData');
        return locale === 'en' ? `${number(parsed * 100)}%` : `${number(parsed * 100)} %`;
    };
    return { t, number, date, conviction };
}

function events(count: number | null | undefined, t: TranslateFn, locale: Locale) {
    if (count == null) return t('propicks.paper.eventsNa');
    return t(count === 1 ? 'propicks.paper.eventOne' : 'propicks.paper.eventMany', { count: formatNumber(count, { maximumFractionDigits: 0 }, undefined, locale) });
}

/** Qué tesis evaluaba la operación simulada; avisa si la tesis ha cambiado desde entonces. */
export function PaperThesisLine({ trade, locale = DEFAULT_LOCALE }: { trade: PaperTradeView; locale?: Locale }) {
    const t = createTranslator(locale);
    const anchor = trade.thesis_anchor;
    const thesisHref = `/research/${encodeURIComponent(trade.ticker)}?view=thesis`;
    if (!anchor) {
        return <p className="text-xs text-gray-400">
            {trade.thesis_version_id === undefined
                ? t('propicks.paper.thesisUnavailable')
                : t('propicks.paper.thesisNotAnchored')}
        </p>;
    }
    return <p className="text-xs text-gray-400">
        {t('propicks.paper.evaluatedThesis', { version: anchor.version })}{anchor.created_at ? t('propicks.paper.evaluatedOn', { date: new Date(anchor.created_at).toLocaleDateString(tag(locale), { timeZone: 'Europe/Madrid' }) }) : ''}.{' '}
        {anchor.superseded
            ? <span className="text-amber-200">{t('propicks.paper.superseded', { latest: anchor.latest_version })}</span>
            : t('propicks.paper.stillCurrent')}{' '}
        <a className="text-teal-300 underline decoration-gray-700 underline-offset-4 hover:text-teal-200" href={thesisHref}>{t('propicks.paper.viewThesis')}</a>
    </p>;
}

export function PaperProposalCard({ trade, locale = DEFAULT_LOCALE }: { trade: PaperTradeView; locale?: Locale }) {
    const { t, number, date, conviction } = formatters(locale);
    const direction = t(trade.direction === 'long' ? 'propicks.paper.long' : trade.direction === 'short' ? 'propicks.paper.short' : 'propicks.paper.noDirection');
    const horizon = t(trade.horizon === 'five_years' ? 'propicks.paper.horizonFive' : trade.horizon === 'short' ? 'propicks.paper.horizonShort' : 'propicks.paper.noHorizon');
    const currency = trade.currency || t('propicks.paper.noCurrency');
    return <article className="min-w-0 space-y-4 rounded-lg border border-gray-700 p-4 text-sm text-gray-300" aria-label={t('propicks.paper.cardLabel', { ticker: trade.ticker })}>
        <div className="flex flex-wrap justify-between gap-2"><h3 className="font-semibold text-gray-100">{trade.ticker} · {direction} · {horizon}</h3><span>{stateLabel[trade.status] ? t(stateLabel[trade.status]) : t('propicks.paper.statusUnknown')}</span></div>
        <p className="text-xs text-gray-400">{t('propicks.paper.notAnOrder')}</p>
        <section aria-label={t('propicks.paper.modelProposal')} className="space-y-2">
            <h4 className="font-medium text-teal-300">{t('propicks.paper.modelProposal')} · {currency}</h4>
            <p className="break-words whitespace-pre-wrap">{trade.thesis || t('propicks.paper.thesisMissing')}</p>
            <dl className="grid min-w-0 grid-cols-2 gap-2 sm:grid-cols-4">
                <div><dt>{t('propicks.paper.proposedEntry')}</dt><dd>{number(trade.proposed_entry)}</dd></div>
                <div><dt>{t('propicks.paper.proposedStop')}</dt><dd>{number(trade.stop)}</dd></div>
                <div><dt>{t('propicks.paper.proposedTarget')}</dt><dd>{number(trade.target)}</dd></div>
                <div><dt>{t('propicks.paper.conviction')}</dt><dd>{conviction(trade.conviction)}</dd></div>
            </dl>
            <p className="text-xs text-gray-400">{t('propicks.paper.convictionNote')}</p>
            <p className="break-words whitespace-pre-wrap">{t('propicks.paper.reasoning', { value: trade.inference_basis || t('propicks.paper.noData') })}</p>
            <PaperThesisLine locale={locale} trade={trade} />
            <p className="text-xs text-gray-400">{t('propicks.paper.created', { date: date(trade.created_at) })}</p>
        </section>
        <section aria-label={t('propicks.paper.observedPrices')} className="space-y-2 border-t border-gray-700 pt-3">
            <h4 className="font-medium text-gray-100">{t('propicks.paper.observedPrices')} · {currency}</h4>
            <dl className="grid min-w-0 gap-2 sm:grid-cols-3">
                <div><dt>{t('propicks.paper.simEntry')}</dt><dd>{number(trade.entry_price)}</dd><dd className="text-xs text-gray-400">{date(trade.entry_at)}</dd></div>
                <div><dt>{t('propicks.paper.lastPrice')}</dt><dd>{number(trade.mark_price)}</dd><dd className="text-xs text-gray-400">{date(trade.mark_at)}</dd></div>
                <div><dt>{t('propicks.paper.simExit')}</dt><dd>{number(trade.exit_price)}</dd><dd className="text-xs text-gray-400">{date(trade.exit_at)}</dd></div>
            </dl>
            <p className="break-words">{t('propicks.paper.priceSource', { source: trade.price_source || t('propicks.paper.noData') })}</p>
            <p>{t('propicks.paper.quantity', { value: number(trade.quantity) })}</p>
            <p>{t('propicks.paper.grossResult', { value: number(trade.status === 'closed' ? trade.realized_pnl : trade.unrealized_pnl), currency: trade.currency || '' })}</p>
            <p>{t('propicks.paper.netResult', { value: number(trade.status === 'closed' ? trade.realized_pnl_net : trade.unrealized_pnl_net), currency: trade.currency || '' })}</p>
            {trade.cost_label === 'supuesto' && <p className="text-xs text-gray-400">{t('propicks.paper.costs', { entry: number(trade.entry_fee), exit: trade.status === 'closed' ? number(trade.exit_fee) : t('propicks.paper.exitEstimated') })}</p>}
            {(trade.dividends_count || trade.dividends_uncertain || trade.dividends_wrong_currency) ? <p className="text-xs text-gray-400">
                {t('propicks.paper.dividends', { total: number(trade.dividends_total), currency: trade.currency || '', events: events(trade.dividends_count, t, locale), source: trade.dividends_source ? t('propicks.paper.dividendSource', { source: trade.dividends_source }) : '' })}
                {trade.dividends_uncertain ? t('propicks.paper.uncertain', { count: trade.dividends_uncertain }) : ''}
                {trade.dividends_wrong_currency ? t('propicks.paper.wrongCurrency', { count: trade.dividends_wrong_currency }) : ''}
            </p> : null}
            {trade.split_adjustments ? <p className="text-xs text-gray-400">{t('propicks.paper.splitAdjusted', { value: trade.last_corporate_action || t('propicks.paper.adjustmentRecorded') })}</p> : null}
            {trade.corporate_action_warning ? <p role="status" className="text-amber-200">{warningLabel[trade.corporate_action_warning] ? t(warningLabel[trade.corporate_action_warning]) : t('propicks.paper.corporateAction', { value: trade.corporate_action_warning })}</p> : null}
            {trade.status === 'closed' && <p>{t('propicks.paper.closeReason', { value: trade.close_reason ? (closeLabel[trade.close_reason] ? t(closeLabel[trade.close_reason]) : t('propicks.paper.otherReason')) : t('propicks.paper.noData') })}</p>}
        </section>
    </article>;
}
