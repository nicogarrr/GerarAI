import Link from 'next/link';

import { Panel } from '@/components/ui/panel';
import type { CompanyHoldingContext } from '@/lib/actions/portfolio.actions';
import { addTransactionHref } from '@/lib/portfolio/add-dialog-link';
import { createFormatters, isValidCurrencyCode, type Formatters } from '@/lib/format';
import { DEFAULT_LOCALE, type Locale } from '@/lib/i18n/locale';
import { createTranslator } from '@/lib/i18n/translate';

const money = (fmt: Formatters, value: number | null, currency: string) =>
    value === null || !isValidCurrencyCode(currency) ? null : fmt.formatMoney(value, currency, { signDisplay: 'auto' });

/**
 * La posición real (IBKR o manual) dentro de la ficha: la tesis y la decisión
 * se leen junto a lo que de verdad tienes. Mismas cifras y avisos que Cartera
 * (coste en revisión, valoración en suspensión, divisa sin tipo de cambio);
 * nada se rellena con ceros.
 */
export function CompanyPositionPanel({ context, locale = DEFAULT_LOCALE }: { context: CompanyHoldingContext | null; locale?: Locale }) {
    if (context === null || context.status === 'not_held') return null;
    const t = createTranslator(locale);
    const fmt = createFormatters(locale);
    const { formatDate, formatNumber, formatPercent, formatPrice } = fmt;
    const NA = fmt.na;
    if (context.status === 'error') {
        return <Panel density="compact" title={t('research.positionPanel.title')}>
            <p className="text-sm text-amber-200" role="status">{context.message} {t('research.positionPanel.errorHint')}</p>
            <Link className="mt-2 inline-flex min-h-11 items-center text-sm text-teal-300 underline decoration-gray-700 underline-offset-4 hover:text-teal-200" href="/portfolio">{t('research.positionPanel.goToPortfolio')}</Link>
        </Panel>;
    }
    const { holding, weightPercent, positionsAsOf } = context;
    const base = holding.baseCurrency;
    const native = holding.nativeCurrency;
    const valueKnown = !holding.valueMissing && !holding.valuationHold;
    // Coste nativo (precio medio en la divisa del valor) y coste en divisa base
    // son dos datos distintos: si solo falta el tipo de cambio histórico de una
    // compra, el coste medio sigue siendo conocido y no se rotula «desconocido».
    const nativeCostKnown = !holding.costReviewMessage && holding.avgPrice > 0;
    const costKnown = nativeCostKnown && holding.cost > 0;
    const value = valueKnown ? money(fmt, holding.value, base) : null;
    const gain = valueKnown && costKnown && !holding.quoteMissing ? money(fmt, holding.gain, base) : null;
    const nativeGain = nativeCostKnown && !holding.valuationHold && !holding.quoteMissing && native !== base ? money(fmt, holding.nativeGain, native) : null;
    const asOf = positionsAsOf ? formatDate(positionsAsOf) : null;
    return <Panel density="compact" description={asOf ? t('research.positionPanel.asOf', { date: asOf }) : t('research.positionPanel.noDate')} title={t('research.positionPanel.title')}>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-3">
            <div><dt className="text-gray-500">{t('research.positionPanel.shares')}</dt><dd className="font-semibold text-gray-100">{formatNumber(holding.quantity, { maximumFractionDigits: 6 })}</dd></div>
            <div><dt className="text-gray-500">{t('research.positionPanel.avgCost')}</dt><dd className="font-semibold text-gray-100">
                {holding.costReviewMessage ? t('research.positionPanel.inReview') : !nativeCostKnown ? NA : isValidCurrencyCode(native) ? formatPrice(holding.avgPrice, native) : formatNumber(holding.avgPrice)}
            </dd></div>
            <div><dt className="text-gray-500">{t('research.positionPanel.value')}</dt><dd className="font-semibold text-gray-100">{value ?? NA}</dd></div>
            <div><dt className="text-gray-500">{t('research.positionPanel.unrealizedGain')}</dt><dd className={`font-semibold ${gain === null ? 'text-gray-100' : holding.gain > 0 ? 'text-emerald-300' : holding.gain < 0 ? 'text-red-300' : 'text-gray-100'}`}>
                {gain ? `${gain} (${formatPercent(holding.gainPercent, { fromRatio: false, signDisplay: 'always' })})` : NA}
            </dd>{nativeGain ? <dd className="text-xs text-gray-400">{t('research.positionPanel.nativeGain', { amount: nativeGain, currency: native })}</dd> : null}</div>
            <div><dt className="text-gray-500">{t('research.positionPanel.weight')}</dt><dd className="font-semibold text-gray-100">{weightPercent === null ? NA : formatPercent(weightPercent, { fromRatio: false })}</dd>
                {weightPercent !== null ? <dd className="text-xs text-gray-400">{t('research.positionPanel.weightNote')}</dd> : null}</div>
            {holding.firstBuyDate ? <div><dt className="text-gray-500">{t('research.positionPanel.firstBuy')}</dt><dd className="font-semibold text-gray-100">{formatDate(holding.firstBuyDate)}</dd></div> : null}
        </dl>
        {holding.valuationHold ? <p className="mt-3 text-xs text-amber-200" role="status">{t('research.positionPanel.valuationHold', { reason: holding.valuationHold.reason })}</p> : null}
        {holding.quoteMissing && !holding.valuationHold ? <p className="mt-3 text-xs text-amber-200" role="status">{t('research.positionPanel.noQuote')}</p> : null}
        {!holding.valuationHold && holding.valueMissing ? <p className="mt-3 text-xs text-amber-200" role="status">{t('research.positionPanel.noValue', { currency: base })}</p> : null}
        {!nativeCostKnown && !holding.costReviewMessage ? <p className="mt-3 text-xs text-amber-200" role="status">{t('research.positionPanel.costUnknown')}</p> : null}
        {nativeCostKnown && !costKnown ? <p className="mt-3 text-xs text-amber-200" role="status">{t('research.positionPanel.noBaseCost', { currency: base })}</p> : null}
        {holding.costReviewMessage ? <p className="mt-3 text-xs text-amber-200" role="status">{holding.costReviewMessage}</p> : null}
        {/* Comprar más o vender desde la ficha abre el alta con el símbolo ya
            elegido; antes había que ir a Cartera, abrir «Añadir inversión» y
            volver a buscar la empresa. */}
        <div className="mt-2 flex flex-wrap gap-x-6">
            <Link className="inline-flex min-h-11 items-center text-sm text-teal-300 underline decoration-gray-700 underline-offset-4 hover:text-teal-200" href={addTransactionHref(holding.symbol)}>{t('research.positionPanel.recordTrade')}</Link>
            <Link className="inline-flex min-h-11 items-center text-sm text-teal-300 underline decoration-gray-700 underline-offset-4 hover:text-teal-200" href="/portfolio">{t('research.positionPanel.viewInPortfolio')}</Link>
        </div>
    </Panel>;
}
