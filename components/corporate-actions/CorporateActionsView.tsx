'use client';

import { useState } from 'react';
import { CheckCircle2, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { RecordList, researchHrefFor, type DataRecord, type ReplaceRecord } from '@/components/data/RecordViews';
import { applyCorporateAction, getCorporateActions } from '@/lib/actions/corporate-actions.actions';
import { showErrorToast } from '@/lib/toast';
import { formatNumber, formatMoney, formatMarketDate } from '@/lib/format';
import { t } from '@/lib/i18n/t';
import { toast } from 'sonner';

interface CorporateActionsViewProps {
    initialActions: DataRecord[];
    emptyMessage?: string;
    ticker?: string | null;
}

/** Etiquetas visibles de esas columnas. Sin este mapa el usuario leía
 *  `ticker · action_type · description · effective_date · ratio` en crudo. */
const CORPORATE_ACTION_LABELS: Record<string, string> = {
    ticker: t('common.labels.ticker'),
    action_type: 'Tipo de acción',
    description: 'Descripción',
    effective_date: 'Fecha de efecto',
    ratio: 'Ratio',
    applied: 'Aplicada',
    applied_at: 'Aplicada el',
};

/** action_type del backend (CorporateActionInput: split|reverse_split|
 *  ticker_change|merger|spin_off). Desconocido -> tal cual, nunca inventado. */
const CORPORATE_ACTION_TYPE_LABELS: Record<string, string> = {
    split: 'Split',
    reverse_split: 'Split inversa',
    ticker_change: 'Cambio de ticker',
    merger: 'Fusión',
    spin_off: 'Spin-off',
    dividend: 'Dividendo',
};

function recordActionId(record: DataRecord): number {
    const value = record.id ?? record.action_id;
    const parsed = typeof value === 'number' ? value : Number(value);
    return Number.isFinite(parsed) ? parsed : NaN;
}

/** El backend no manda `status`: el estado vive en `applied` / `applied_at`. */
function isApplied(record: DataRecord): boolean {
    if (record.applied === true) return true;
    if (record.applied === false) return false;
    return typeof record.applied_at === 'string' && record.applied_at !== '';
}

export default function CorporateActionsView({ initialActions, emptyMessage, ticker }: CorporateActionsViewProps) {
    const [applyingId, setApplyingId] = useState<number | null>(null);

    // Filtro por empresa al llegar desde la ficha (?ticker=): se aplica a la
    // lista inicial Y a cada refetch, o la tabla volveria a mostrar todas las
    // empresas tras aplicar una accion.
    const matchesTicker = (record: DataRecord): boolean =>
        !ticker || String(record.ticker ?? '').toUpperCase() === ticker;
    const visibleActions = initialActions.filter(matchesTicker);

    const handleApply = async (record: DataRecord, replace: ReplaceRecord) => {
        const actionId = recordActionId(record);
        if (!Number.isFinite(actionId)) {
            toast.error('La acción corporativa no tiene un identificador válido');
            return;
        }
        setApplyingId(actionId);
        try {
            // El registro aplicado lo devuelve el backend (applied/applied_at):
            // la fila se pinta con ESA respuesta. Antes solo se mostraba un
            // toast y la fila seguía con el botón «Aplicar» habilitado hasta
            // un refresco manual.
            const appliedRecord = await applyCorporateAction(actionId);
            replace(appliedRecord);
            toast.success('Acción corporativa aplicada a la cartera');
        } catch (error) {
            showErrorToast(error, { onRetry: () => handleApply(record, replace) });
        } finally {
            setApplyingId(null);
        }
    };

    return (
        <div className="[&_a.font-mono]:inline-flex [&_a.font-mono]:min-h-11 [&_a.font-mono]:min-w-11 [&_a.font-mono]:items-center">
        <RecordList
            title="Acciones Corporativas"
            // La página ya muestra título, descripción y recuento: no se repiten en la tarjeta.
            hideTitle
            records={visibleActions}
            fetchRecords={async () => (await getCorporateActions()).filter(matchesTicker)}
            // Columnas que sí sirve GET /api/corporate-actions
            // (corporate_actions._payload). `status` no está en ese payload:
            // la columna se pintaba siempre a «—».
            columns={['ticker', 'action_type', 'description', 'effective_date', 'ratio', 'applied']}
            columnLabels={CORPORATE_ACTION_LABELS}
            formatColumns={{
                action_type: (value) =>
                    typeof value === 'string'
                        ? CORPORATE_ACTION_TYPE_LABELS[value] ?? value
                        : String(value ?? '—'),
                effective_date: (value) => formatMarketDate(value as string | null),
                description: (value, record) => record.action_type === 'dividend' && typeof record.amount_per_share === 'number' && typeof record.currency === 'string'
                    ? `Dividendo de ${formatMoney(record.amount_per_share, record.currency)} por acción${record.pay_date ? ` · pago ${formatMarketDate(record.pay_date as string)}` : ''} · fuente ${record.source ?? 'N/D'}${record.source === 'yahoo_finance' ? ' (importe ajustado por splits)' : ''}`
                    : String(value ?? 'N/D'),
                ratio: (value) => formatNumber(value as number | string | null, { maximumFractionDigits: 4 }),
            }}
            emptyMessage={emptyMessage ?? (ticker ? `Sin eventos pendientes de ${ticker}.` : 'Sin eventos pendientes.')}
            linkColumns={{ ticker: (record) => researchHrefFor(record) }}
            rowActions={(record, _index, replace) => {
                const actionId = recordActionId(record);
                // Dividendo declarado del proveedor: solo informativo, el cobro
                // se registra a mano en la cartera.
                if (record.action_type === 'dividend') {
                    return record.declared === false
                        ? <span className="text-xs text-amber-400/90">Importe incierto</span>
                        : <span className="text-xs text-gray-500">Del proveedor</span>;
                }
                if (isApplied(record)) {
                    return (
                        <span className="inline-flex items-center gap-1.5 text-xs text-gray-500">
                            <CheckCircle2 className="h-4 w-4 text-teal-400" />
                            Aplicada
                        </span>
                    );
                }
                // Split anterior a tu primera operación: tus acciones ya se
                // compraron después, así que está reflejado y no se aplica.
                if (record.historical === true) {
                    return (
                        <span className="text-xs text-gray-500">Histórico, ya reflejado</span>
                    );
                }
                // Empresa fuera de tu cartera: no hay posición ni operaciones que ajustar.
                if (record.no_position === true) {
                    return (
                        <span className="text-xs text-gray-500">Sin posición: nada que ajustar</span>
                    );
                }
                return (
                    <Button
                        size="sm"
                        variant="outline"
                        disabled={!Number.isFinite(actionId) || applyingId === actionId}
                        onClick={() => handleApply(record, replace)}
                        className="gap-1.5 border-teal-800 text-teal-300 hover:bg-teal-900/20 hover:text-teal-200"
                    >
                        {applyingId === actionId ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                            <CheckCircle2 className="h-3.5 w-3.5" />
                        )}
                        {t('common.actions.apply')}
                    </Button>
                );
            }}
        />
        </div>
    );
}
