import Link from 'next/link';
import { Card, CardContent } from '@/components/ui/card';
import DcaAlertSettingsList from '@/components/watchlist/DcaAlertSettingsList';
// Los controles siguen diferidos; el disclosure nativo funciona antes de hidratar.
import {
    LazyDcaEvaluateButton as DcaEvaluateButton,
} from '@/components/watchlist/LazyDcaControls';
import { dcaRunSummary } from '@/lib/dca/format';
import type { DcaSignalsResponse } from '@/lib/dca/types';
import { formatCountEs } from '@/lib/format';
import type { Locale } from '@/lib/i18n/locale';
import { t, type TranslationKey, type TranslationVars } from '@/lib/i18n/t';

type TiFn = (key: TranslationKey, vars?: TranslationVars) => string;
/** Fallback español sin RequestScope (tests y render directo): el acceso es de main (lib/i18n/t). */
const esT: TiFn = t;

interface DcaSignalsPanelProps {
    data: DcaSignalsResponse | null;
    unavailable: boolean;
    /** Traductor y locale del idioma elegido (por defecto español). */
    ti?: TiFn;
    locale?: Locale;
}

/** Ajustes de avisos. El veredicto DCA vive en las tarjetas/tabla de la watchlist. */
export default function DcaSignalsPanel({ data, unavailable, ti = esT, locale = 'es' }: DcaSignalsPanelProps) {
    if (unavailable || !data) {
        return (
            <Card className="border-gray-700 bg-gray-800/50" data-testid="dca-signals-unavailable">
                <CardContent className="px-4 py-4 text-sm text-gray-400">
                    {ti('watchlist.dca.panel.unavailable')}
                </CardContent>
            </Card>
        );
    }
    const runSummary = dcaRunSummary(data.last_run);
    const runTone = { ok: 'text-emerald-400', warn: 'text-amber-300', error: 'text-red-300', neutral: 'text-gray-400' }[runSummary.tone];
    const channels = data.channels.map((channel) => (channel === 'in_app' ? 'app' : channel === 'email' ? ti('watchlist.dca.panel.channelEmail') : channel));
    return (
        <details className="group rounded-lg border border-gray-700 bg-gray-800/30" data-testid="dca-signals">
            <summary className="min-h-11 cursor-pointer rounded-lg px-4 py-3 text-sm font-semibold text-gray-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-400">
                {ti('watchlist.dca.panel.title')}
                <span className="ml-2 text-xs font-normal text-gray-400">({formatCountEs(data.items.length, ti('watchlist.dca.panel.companyOne'), ti('watchlist.dca.panel.companyOther'), locale)})</span>
            </summary>
            <div className="space-y-3 px-4 pb-4">
                <Link href="/settings#dca" className="inline-flex min-h-11 items-center text-sm text-teal-300 underline">{ti('watchlist.dca.panel.settingsLink')}</Link>
                <p className="text-xs text-gray-400">{ti('watchlist.dca.panel.noOrders')}</p>
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="min-w-0">
                        <p className="text-xs text-gray-500">
                            {data.directional_policy
                                ? ti('watchlist.dca.panel.directional', {
                                    up: data.up_min_level ? ti('watchlist.dca.panel.upFrom', { level: data.up_min_level }) : ti('watchlist.dca.panel.off'),
                                    down: data.down_max_level ? ti('watchlist.dca.panel.downTo', { level: data.down_max_level }) : ti('watchlist.dca.panel.off'),
                                })
                                : ti('watchlist.dca.panel.globalMin', { level: data.global_min_level })} ·{' '}
                            {data.trims_enabled ? ti('watchlist.dca.panel.trimsOn') : ti('watchlist.dca.panel.trimsOff')} · {ti('watchlist.dca.panel.channels', { list: channels.join(', ') })}
                            {data.channels.includes('email') && !data.email_configured ? ti('watchlist.dca.panel.emailMissing') : ''}
                            {data.alerts_enabled ? '' : ti('watchlist.dca.panel.alertsOff')}
                        </p>
                        {data.last_run !== undefined ? (
                            <p className={`text-xs ${runTone}`} data-testid="dca-last-run" role="status">{runSummary.text}</p>
                        ) : null}
                    </div>
                    <DcaEvaluateButton />
                </div>
                {data.evaluation_enabled === false && data.items.length > 0 ? (
                    <p className="rounded-md border border-amber-800/60 bg-amber-950/30 px-3 py-2 text-sm text-amber-200" data-testid="dca-evaluation-disabled" role="status">
                        {data.items.some((item) => item.state)
                            ? ti('watchlist.dca.panel.evalOffStale')
                            : ti('watchlist.dca.panel.evalOffEmpty')}
                    </p>
                ) : null}
                <DcaAlertSettingsList items={data.items} />
                <p className="text-[11px] text-gray-500">
                    {ti('watchlist.dca.panel.legend')}
                </p>
            </div>
        </details>
    );
}
