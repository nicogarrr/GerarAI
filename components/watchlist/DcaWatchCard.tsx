import type { DcaWatchCardData } from '@/lib/dca/types';
import { dcaEngineText } from '@/lib/dca/engine-text';
import { readableInk } from '@/lib/dca/readable-ink';
import { createFormatters } from '@/lib/format';
import { dcaPrice } from '@/lib/dca/format';
import type { Locale } from '@/lib/i18n/locale';
import type { TranslateFn } from '@/lib/i18n/translate';

const RISK_TONE: Record<string, string> = {
    low: 'border-teal-700 text-teal-300',
    medium: 'border-amber-700 text-amber-300',
    high: 'border-red-700 text-red-300',
};

function chipStyle(color: string, fg: string) {
    return { backgroundColor: color, color: readableInk(color, fg), borderColor: color === '#FFFFFF' ? '#9CA3AF' : color };
}

/**
 * Tarjeta DCA de un valor de la watchlist: nivel por marco temporal (S/M/T/A),
 * nivel actual con los meses que lleva en la zona, riesgo, movimiento desde el
 * último cambio y «¿Por qué?» con las entradas de la fórmula. Colores y
 * nombres de zona: los de GerarAI (vienen del motor).
 */
const TF_KEYS = {
    week: 'watchlist.dcaCard.tf.week',
    month: 'watchlist.dcaCard.tf.month',
    quarter: 'watchlist.dcaCard.tf.quarter',
    year: 'watchlist.dcaCard.tf.year',
} as const;

const TF_SHORT_KEYS = {
    week: 'watchlist.dcaCard.tfShort.week',
    month: 'watchlist.dcaCard.tfShort.month',
    quarter: 'watchlist.dcaCard.tfShort.quarter',
    year: 'watchlist.dcaCard.tfShort.year',
} as const;

const RISK_KEYS = {
    low: 'watchlist.dcaCard.risk.low',
    medium: 'watchlist.dcaCard.risk.medium',
    high: 'watchlist.dcaCard.risk.high',
} as const;

const BINDING_KEYS = {
    drawdown: 'watchlist.dcaCard.binding.drawdown',
    sma_gap: 'watchlist.dcaCard.binding.smaGap',
    empate: 'watchlist.dcaCard.binding.empate',
} as const;

const RISK_REASON_KEYS = {
    volatility: 'watchlist.dcaCard.riskReason.volatility',
    volatility_unknown: 'watchlist.dcaCard.riskReason.volatilityUnknown',
    pre_revenue: 'watchlist.dcaCard.riskReason.preRevenue',
    short_history: 'watchlist.dcaCard.riskReason.shortHistory',
    stale: 'watchlist.dcaCard.riskReason.stale',
} as const;

export default function DcaWatchCard({ data, ti, locale }: { data: DcaWatchCardData | null; ti: TranslateFn; locale: Locale }) {
    if (!data) return <p className="text-xs text-gray-400" role="status">{ti('watchlist.dcaCard.unavailable')}</p>;
    if (!data.available || !data.current) return <p className="text-xs text-gray-400" role="status">{ti('watchlist.dcaCard.notEnough')}</p>;
    const f = createFormatters(locale);
    const pct = (v: number | null | undefined, sign = false) => (v === null || v === undefined ? '—' : f.formatPercent(v, { fromRatio: true, digits: 1, signDisplay: sign ? 'always' : 'auto' }));
    // Mismo formato de importe que el resto de la app («413,96 US$»), con el helper compartido de lib/dca/format.
    const price = (v: number | null | undefined) => dcaPrice(v, data, locale) ?? '—';
    const cur = data.current;
    const change = data.last_change;
    const why = data.why;
    const risk = data.risk;
    const live = data.live;
    // Hora de mercado (ET), con zona explicita: formatDateTime usaria la zona del proceso y romperia SSR/hidratacion.
    const liveTime = live?.used && live.timestamp ? f.formatMarketDateTime(new Date(live.timestamp * 1000), { hour: '2-digit', minute: '2-digit' }) : null;
    const liveLine = live?.used
        ? ti(live.session === 'pre' ? 'watchlist.dcaCard.livePre' : live.session === 'post' ? 'watchlist.dcaCard.livePost' : 'watchlist.dcaCard.liveRegular', {
            price: price(live.price),
            time: liveTime ?? '—',
        })
        : null;
    // Mercado cerrado ("closed") no es un dato que falte: el cierre es lo más fresco.
    const liveWarning = live && !live.used && live.reason !== 'closed'
        ? ti(live.reason === 'currency_mismatch' || live.reason === 'out_of_band' ? 'watchlist.dcaCard.liveDiscarded' : 'watchlist.dcaCard.liveMissing', {
            date: f.formatDate(cur.signal_date),
        })
        : null;
    return (
        <section aria-label={ti('watchlist.dcaCard.label', { symbol: data.symbol })} className="space-y-3 rounded-lg border border-gray-700 bg-gray-900/60 p-3" data-testid="dca-watch-card">
            <ul aria-label={ti('watchlist.dcaCard.timeframes')} className="flex flex-wrap gap-1.5">
                {data.timeframes.map((tf) => (
                    <li key={tf.key}>
                        {tf.available && tf.zone ? (
                            <span
                                className="inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] font-semibold"
                                style={chipStyle(tf.zone.color, tf.zone.fg)}
                                title={`${ti(TF_KEYS[tf.key as keyof typeof TF_KEYS])}: ${dcaEngineText(tf.zone.label, ti)}`}
                                data-testid={`dca-tf-${tf.key}`}
                            >
                                {/* Sin opacity-XX: dejaba la etiqueta a 3,37:1 sobre zonas oscuras (#B400FF), bajo WCAG AA. */}
                                <span>{ti(TF_SHORT_KEYS[tf.key as keyof typeof TF_SHORT_KEYS])}</span>
                                {tf.zone.key.toUpperCase().replace('-TRIM', '')}
                            </span>
                        ) : (
                            <span className="inline-flex items-center rounded-md border border-gray-700 px-2 py-0.5 text-[11px] text-gray-500" title={ti('watchlist.dcaCard.tfMissing')} data-testid={`dca-tf-${tf.key}`}>
                                {ti(TF_SHORT_KEYS[tf.key as keyof typeof TF_SHORT_KEYS])} —
                            </span>
                        )}
                    </li>
                ))}
            </ul>
            <div className="flex flex-wrap items-center gap-2">
                <span className="inline-flex items-center rounded-full border px-3 py-1 text-sm font-semibold" style={chipStyle(cur.color, cur.fg)} data-testid="dca-card-current">
                    {dcaEngineText(cur.label, ti)} · {dcaEngineText(cur.zone, ti)} · {ti('watchlist.dcaCard.monthsInZone', { count: cur.months_in_zone })}
                </span>
                {risk ? <span className={`rounded-full border px-2 py-0.5 text-xs ${RISK_TONE[risk.key] ?? ''}`} data-testid="dca-card-risk">{ti(RISK_KEYS[risk.key as keyof typeof RISK_KEYS])}</span> : null}
                {cur.status === 'forming' ? <span className="text-[11px] text-gray-400">{ti('watchlist.dcaCard.forming')}</span> : null}
            </div>
            {liveLine ? (
                <p className="text-xs text-gray-300" data-testid="dca-card-live">
                    {liveLine} <span className="text-gray-500">· {ti('watchlist.dcaCard.liveNote')}</span>
                </p>
            ) : null}
            {liveWarning ? <p className="text-xs text-amber-300" role="status" data-testid="dca-card-live-missing">{liveWarning}</p> : null}
            {change ? (
                <p className="text-xs text-gray-300" data-testid="dca-card-change">
                    {ti('watchlist.dcaCard.sinceChange', {
                        change: pct(change.change, true),
                        from: dcaEngineText(change.from.label, ti),
                        price: price(change.close),
                        date: f.formatDate(change.signal_date),
                    })}
                </p>
            ) : <p className="text-xs text-gray-400">{ti('watchlist.dcaCard.noChange')}</p>}
            {why ? (
                <details className="text-xs text-gray-300">
                    <summary className="flex min-h-11 cursor-pointer items-center font-medium text-teal-300">{ti('watchlist.dcaCard.why')}</summary>
                    <ul className="mt-1 space-y-1">
                        <li>{ti('watchlist.dcaCard.whyDrawdown', { dd: pct(why.drawdown), high: price(why.high), months: why.high_lookback_months, t2: pct(why.dd_thresholds[0]), t3: pct(why.dd_thresholds[1]), t4: pct(why.dd_thresholds[2]), level: why.level_drawdown ? `${why.level_drawdown}X` : '—' })}</li>
                        {why.sma !== null ? <li>{ti('watchlist.dcaCard.whySma', { gap: pct(why.sma_gap), sma: price(why.sma), months: why.sma_months ?? '—', adj: pct(why.adj_gap), level: why.level_sma_gap ? `${why.level_sma_gap}X` : '—' })}</li> : null}
                        {why.vol !== null ? <li>{ti('watchlist.dcaCard.whyVol', { vol: pct(why.vol), ref: pct(why.vol_ref) })}</li> : null}
                        <li>{ti('watchlist.dcaCard.whyBinding', { binding: ti(BINDING_KEYS[(why.binding ?? 'drawdown') as keyof typeof BINDING_KEYS] ?? BINDING_KEYS.drawdown) })}</li>
                        <li>{ti('watchlist.dcaCard.whyPrices', { prices: (['2x', '3x', '4x'] as const).map((k) => `${k.toUpperCase()} ${price(why.level_prices[k])}`).join(' · ') })}</li>
                        {risk ? <li>{ti('watchlist.dcaCard.whyRisk', { reasons: risk.reasons.map((r) => (r.key in RISK_REASON_KEYS ? ti(RISK_REASON_KEYS[r.key as keyof typeof RISK_REASON_KEYS], { value: r.key === 'volatility' ? pct(r.value) : String(r.value ?? '') }) : r.key)).join(' · ') })}</li> : null}
                        <li className="text-gray-500">{ti('watchlist.dcaCard.whyOfficial')}</li>
                    </ul>
                </details>
            ) : null}
        </section>
    );
}
