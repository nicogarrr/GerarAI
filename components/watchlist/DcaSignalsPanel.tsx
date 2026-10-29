import Link from 'next/link';
import { Card, CardContent } from '@/components/ui/card';
import DcaAlertSettingsList from '@/components/watchlist/DcaAlertSettingsList';
// Los controles siguen diferidos; el disclosure nativo funciona antes de hidratar.
import {
    LazyDcaEvaluateButton as DcaEvaluateButton,
} from '@/components/watchlist/LazyDcaControls';
import { dcaRunSummary } from '@/lib/dca/format';
import type { DcaSignalsResponse } from '@/lib/dca/types';

interface DcaSignalsPanelProps {
    data: DcaSignalsResponse | null;
    unavailable: boolean;
}

/** Ajustes de avisos. El veredicto DCA vive en las tarjetas/tabla de la watchlist. */
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
        <details className="group rounded-lg border border-gray-700 bg-gray-800/30" data-testid="dca-signals">
            <summary className="min-h-11 cursor-pointer rounded-lg px-4 py-3 text-sm font-semibold text-gray-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-400">
                Avisos DCA e histórico
                <span className="ml-2 text-xs font-normal text-gray-400">({data.items.length} empresas)</span>
            </summary>
            <div className="space-y-3 px-4 pb-4">
                <Link href="/settings#dca" className="inline-flex min-h-11 items-center text-sm text-teal-300 underline">Configurar avisos DCA en Ajustes →</Link>
                <p className="text-xs text-gray-400">No cambia el veredicto ni realiza órdenes.</p>
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="min-w-0">
                        <p className="text-xs text-gray-500">
                            {data.directional_policy
                                ? `Subida: ${data.up_min_level ? `desde ${data.up_min_level}X` : 'desactivada'} · bajada: ${data.down_max_level ? `hasta ${data.down_max_level}X` : 'desactivada'}`
                                : `Aviso mínimo global ${data.global_min_level}X`} ·
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
                <DcaAlertSettingsList items={data.items} />
                <p className="text-[11px] text-gray-500">
                    1X = aportación base; 2X-4X = múltiplos de tu aportación mensual. Fórmula propia y transparente, no la de DCA
                    Optimizer. Apoyo a la decisión, no asesoramiento financiero.
                </p>
            </div>
        </details>
    );
}
