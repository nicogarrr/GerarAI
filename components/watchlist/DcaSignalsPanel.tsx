import { Card, CardContent } from '@/components/ui/card';
import DcaLevelBadge from '@/components/watchlist/DcaLevelBadge';
// Las islas interactivas del panel (evaluar a mano, detalle de aciertos y
// aviso mínimo por símbolo) cargan diferidas (ver LazyDcaControls) para que
// no viajen en el JS inicial de /watchlist; el contenido del panel sigue SSR.
import {
    LazyDcaEvaluateButton as DcaEvaluateButton,
    LazyDcaHitRatesPopover as DcaHitRatesPopover,
    LazyDcaMinLevelSelect as DcaMinLevelSelect,
} from '@/components/watchlist/LazyDcaControls';
import { dcaRunSummary } from '@/lib/dca/format';
import type { DcaSignalsResponse } from '@/lib/dca/types';

interface DcaSignalsPanelProps {
    data: DcaSignalsResponse | null;
    unavailable: boolean;
}

/** Señales DCA por niveles de watchlist + cartera, con su aviso mínimo y la leyenda de zonas. */
export default function DcaSignalsPanel({ data, unavailable }: DcaSignalsPanelProps) {
    if (unavailable || !data) {
        return (
            <Card className="border-gray-700 bg-gray-800/50" data-testid="dca-signals-unavailable">
                <CardContent className="px-4 py-4 text-sm text-gray-400">
                    Señales DCA no disponibles ahora mismo (servicio no disponible).
                </CardContent>
            </Card>
        );
    }
    const runSummary = dcaRunSummary(data.last_run);
    const runTone = { ok: 'text-emerald-400', warn: 'text-amber-300', error: 'text-red-300', neutral: 'text-gray-400' }[runSummary.tone];
    const channels = data.channels.map((channel) => (channel === 'in_app' ? 'app' : channel === 'email' ? 'correo' : channel));
    return (
        <section aria-labelledby="dca-signals-title" className="space-y-3" data-testid="dca-signals">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0">
                    <h2 id="dca-signals-title" className="text-lg font-semibold text-gray-100">Señales de compra periódica (DCA)</h2>
                    <p className="text-xs text-gray-500">
                        Veredicto mensual con cierres diarios asentados · aviso mínimo global {data.global_min_level}X ·
                        recortes {data.trims_enabled ? 'con aviso' : 'sin aviso'} · canales: {channels.join(', ')}
                        {data.channels.includes('email') && !data.email_configured ? ' (correo sin configurar)' : ''}
                        {data.alerts_enabled ? '' : ' · avisos desactivados'}
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
                        ? 'La evaluación diaria automática está desactivada en el servidor: los niveles no se actualizan solos. Pulsa «Ejecutar pendientes ahora» para recalcularlos.'
                        : 'Todavía no hay niveles porque la evaluación diaria automática está desactivada en el servidor. Pulsa «Ejecutar pendientes ahora» para calcularlos con los cierres de hoy.'}
                </p>
            ) : null}
            <ul aria-label="Leyenda de zonas DCA" className="flex flex-wrap gap-2 text-[11px]">
                {data.zones.map((zone) => (
                    <li key={zone.key} className="inline-flex items-center gap-1.5 text-gray-400">
                        <span
                            aria-hidden="true"
                            className="inline-block h-3 w-3 rounded-full border"
                            style={{ backgroundColor: zone.color, borderColor: zone.color === '#FFFFFF' ? '#9CA3AF' : zone.color }}
                        />
                        <span className="font-semibold text-gray-300">{zone.label}</span> {zone.zone}
                    </li>
                ))}
            </ul>
            {data.items.length === 0 ? (
                <p className="text-sm text-gray-500">Añade tickers a la watchlist o a la cartera para ver su nivel DCA.</p>
            ) : (
                <Card className="border-gray-700 bg-gray-800/50">
                    <CardContent className="divide-y divide-gray-800 p-0">
                        {data.items.map((item) => (
                            <div key={item.symbol} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
                                <div className="flex min-w-0 items-center gap-3">
                                    <div className="min-w-0">
                                        <p className="font-semibold text-gray-100">{item.symbol}</p>
                                        {item.company_name ? <p className="max-w-[220px] truncate text-xs text-gray-500" title={item.company_name}>{item.company_name}</p> : null}
                                    </div>
                                    <div className="flex flex-wrap gap-1">
                                        {item.in_watchlist ? <span className="rounded border border-gray-700 px-1.5 text-[10px] text-gray-400">watchlist</span> : null}
                                        {item.in_portfolio ? <span className="rounded border border-teal-800 px-1.5 text-[10px] text-teal-300">en cartera</span> : null}
                                    </div>
                                </div>
                                <div className="flex items-center gap-3">
                                    <DcaLevelBadge item={item} signalMonths={data.signal_months} />
                                    {item.state ? <DcaHitRatesPopover symbol={item.symbol} /> : null}
                                    <DcaMinLevelSelect symbol={item.symbol} override={item.min_level_override} globalMinLevel={data.global_min_level} />
                                </div>
                            </div>
                        ))}
                    </CardContent>
                </Card>
            )}
            <p className="text-[11px] text-gray-500">
                1X = aportación base; 2X-4X = múltiplos de tu aportación mensual. Fórmula propia y transparente, no la de DCA
                Optimizer. Apoyo a la decisión, no asesoramiento financiero.
            </p>
        </section>
    );
}
