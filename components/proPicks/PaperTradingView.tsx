import Link from 'next/link';
import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { PaperProposalCard } from './PaperProposalCard';
import { PaperCalibrationView } from './PaperCalibrationView';
import { feedPaperProposalsNow, getPaperTrading, type PaperState } from '@/lib/actions/paper-trading.actions';
import { DEFAULT_LOCALE, type Locale } from '@/lib/i18n/locale';
import { createTranslator, type TranslateFn } from '@/lib/i18n/translate';

const numberFor = (t: TranslateFn, locale: Locale) => (value: string | number | null) => value === null ? t('propicks.paper.noData') : Number(value).toLocaleString(locale === 'en' ? 'en-US' : 'es-ES', { maximumFractionDigits: 2 });
const horizon = (value: string, t: TranslateFn) => t(value === 'five_years' ? 'propicks.paper.horizonFive' : 'propicks.paper.horizonShort');


function PaperFeedButton({ t }: { t: TranslateFn }) {
    const [state, setState] = useState<'idle' | 'feeding' | 'queued' | 'error'>('idle');
    const handleFeed = async () => {
        setState('feeding');
        let success = false;
        try {
            const result = await feedPaperProposalsNow();
            success = result.success;
        } catch {
            success = false;
        } finally {
            // Un rechazo no puede dejar el botón en «Encolando…» para siempre.
            setState(success ? 'queued' : 'error');
        }
    };
    const loading = state === 'feeding';
    return (
        <div className="flex flex-col items-center gap-2">
            <Button
                onClick={handleFeed}
                disabled={loading || state === 'queued'}
                aria-busy={loading}
            >
                {loading ? t('propicks.paper.feeding') : t('propicks.paper.generate')}
            </Button>
            {state === 'queued' ? (
                <p className="text-sm text-teal-300">{t('propicks.paper.queued')}</p>
            ) : null}
            {state === 'error' ? (
                <p className="text-sm text-red-400">{t('propicks.paper.feedError')}</p>
            ) : null}
        </div>
    );
}

export function PaperTradingContent({ data, locale = DEFAULT_LOCALE }: { data: PaperState; locale?: Locale }) {
    const t = createTranslator(locale);
    const number = numberFor(t, locale);
    if (data.error) return <p role="alert" className="text-red-300">{data.error}</p>;
    return <section className="min-w-0 space-y-4" aria-label={t('propicks.paper.sectionLabel')}>
        <h2 className="text-xl font-semibold text-gray-100">{t('propicks.paper.heading')}</h2>
        <p className="text-sm text-gray-400">{t('propicks.paper.intro')} <Link href="/paper-trading" className="text-teal-300 hover:underline">{t('propicks.paper.demoLink')}</Link>.</p>
        <div className="grid gap-3 sm:grid-cols-2">
            {data.score.groups.map(group => <article key={`${group.horizon}-${group.currency}`} className="rounded-lg border border-gray-700 bg-gray-800/50 p-4">
                <h3 className="font-medium text-teal-300">{horizon(group.horizon, t)} · {group.currency === 'sin_datos' ? t('propicks.paper.noCurrency') : group.currency}</h3>
                <dl className="mt-3 grid grid-cols-2 gap-2 text-sm text-gray-300">
                    <dt>{t('propicks.paper.winsClosed')}</dt><dd>{group.wins} / {group.closed}</dd>
                    <dt>{t('propicks.paper.hitRate')}</dt><dd>{group.hit_rate === null ? t('propicks.paper.noData') : `${number(group.hit_rate * 100)}${locale === 'en' ? '%' : ' %'}`}</dd>
                    <dt>{t('propicks.paper.lossesFlat')}</dt><dd>{group.losses} / {group.flat}</dd>
                    <dt>{t('propicks.paper.grossClosed')}</dt><dd>{number(group.realized_pnl)}</dd>
                    <dt>{t('propicks.paper.grossOpen')}</dt><dd>{number(group.unrealized_pnl)}</dd>
                    <dt>{t('propicks.paper.openNoPrice')}</dt><dd>{group.missing_marks}</dd>
                    <dt>{t('propicks.paper.netClosed')}</dt><dd>{group.realized_pnl_net === null || group.realized_pnl_net === undefined ? t('propicks.paper.noData') : number(group.realized_pnl_net)}</dd>
                    <dt>{t('propicks.paper.closedWithNet')}</dt><dd>{t('propicks.paper.closedNetOf', { net: group.closed_net ?? 0, closed: group.closed })}</dd>
                    <dt>{t('propicks.paper.excludedCorporate')}</dt><dd>{group.closed_distorted ?? 0}</dd>
                </dl>
            </article>)}
        </div>
        <PaperCalibrationView data={data.score.calibracion} locale={locale} />
        {data.trades.length === 0 && (
            <div className="flex flex-col items-center gap-3 rounded-lg border border-gray-700 bg-gray-800/50 p-6 text-center">
                <p className="text-gray-400">{t('propicks.paper.empty')}</p>
                <PaperFeedButton t={t} />
            </div>
        )}
        {data.trades.map(trade => <PaperProposalCard key={trade.id} trade={trade} locale={locale} />)}
        <details className="text-xs text-gray-400"><summary>{t('propicks.paper.basisTitle')}</summary><p className="mt-2">{t('propicks.paper.basisText')}</p></details>
    </section>;
}

export default function PaperTradingView({ locale = DEFAULT_LOCALE }: { locale?: Locale }) {
    const t = createTranslator(locale);
    const [data, setData] = useState<PaperState | null>(null);
    useEffect(() => { let alive = true; getPaperTrading().then(result => { if (alive) setData(result); }).catch(() => { if (alive) setData({ trades: [], score: { groups: [] }, error: createTranslator(locale)('propicks.paper.loadError') }); }); return () => { alive = false; }; }, [locale]);
    return data ? <PaperTradingContent data={data} locale={locale} /> : <p role="status" className="text-gray-400">{t('propicks.paper.loading')}</p>;
}
