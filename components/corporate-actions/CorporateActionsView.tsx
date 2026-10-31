'use client';

import { useState } from 'react';
import { CheckCircle2, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { RecordList, researchHrefFor, type DataRecord, type ReplaceRecord } from '@/components/data/RecordViews';
import { applyCorporateAction, getCorporateActions } from '@/lib/actions/corporate-actions.actions';
import { showErrorToast } from '@/lib/toast';
import { t } from '@/lib/i18n/t';
import { useT, useFormat } from '@/lib/i18n/client';
import type { TranslateFn as TFunction } from '@/lib/i18n/translate';
import type { Formatters } from '@/lib/format';
import { toast } from 'sonner';

interface CorporateActionsViewProps {
    initialActions: DataRecord[];
    emptyMessage?: string;
    ticker?: string | null;
}

/** Etiquetas visibles de esas columnas. Sin este mapa el usuario leía
 *  `ticker · action_type · description · effective_date · ratio` en crudo. */
function corporateActionLabels(ti: TFunction): Record<string, string> {
    return {
        ticker: t('common.labels.ticker'),
        action_type: ti('corporateActions.labels.actionType'),
        description: ti('corporateActions.labels.description'),
        effective_date: ti('corporateActions.labels.effectiveDate'),
        ratio: ti('corporateActions.labels.ratio'),
        applied: ti('corporateActions.labels.applied'),
        applied_at: ti('corporateActions.labels.appliedAt'),
    };
}

/** action_type del backend (CorporateActionInput: split|reverse_split|
 *  ticker_change|merger|spin_off). Desconocido -> tal cual, nunca inventado. */
function corporateActionTypeLabels(ti: TFunction): Record<string, string> {
    return {
        split: ti('corporateActions.types.split'),
        reverse_split: ti('corporateActions.types.reverseSplit'),
        ticker_change: ti('corporateActions.types.tickerChange'),
        merger: ti('corporateActions.types.merger'),
        spin_off: ti('corporateActions.types.spinOff'),
        dividend: ti('corporateActions.types.dividend'),
    };
}

/** Descripción de un dividendo declarado: importe por acción con su divisa,
 *  fecha de pago si consta y matiz de ajuste por splits si aplica. */
function dividendDescription(ti: TFunction, f: Formatters, record: DataRecord, fallback: unknown): string {
    if (record.action_type === 'dividend' && typeof record.amount_per_share === 'number' && typeof record.currency === 'string') {
        return ti('corporateActions.dividend.base', { amount: f.formatMoney(record.amount_per_share, record.currency) })
            + (record.pay_date ? ti('corporateActions.dividend.payDate', { date: f.formatMarketDate(record.pay_date as string) }) : '')
            + (record.source === 'yahoo_finance' ? ti('corporateActions.dividend.adjusted') : '');
    }
    return String(fallback ?? ti('common.na'));
}

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
    const ti = useT();
    const f = useFormat();
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
            toast.error(ti('corporateActions.toast.invalidId'));
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
            toast.success(ti('corporateActions.toast.applied'));
        } catch (error) {
            showErrorToast(error, { onRetry: () => handleApply(record, replace) });
        } finally {
            setApplyingId(null);
        }
    };

    return (
        <div className="[&_a.font-mono]:inline-flex [&_a.font-mono]:min-h-11 [&_a.font-mono]:min-w-11 [&_a.font-mono]:items-center">
        <RecordList
            title={ti('corporateActions.view.title')}
            titleAs="h2"
            // La página ya muestra título, descripción y recuento: no se repiten en la tarjeta.
            hideTitle
            records={visibleActions}
            fetchRecords={async () => (await getCorporateActions()).filter(matchesTicker)}
            // Columnas que sí sirve GET /api/corporate-actions
            // (corporate_actions._payload). `status` no está en ese payload:
            // la columna se pintaba siempre a «—».
            columns={['ticker', 'action_type', 'description', 'effective_date', 'ratio', 'applied']}
            columnLabels={corporateActionLabels(ti)}
            // Sin «fuente yahoo_finance» por dato (regla de Nico, 2026-10-28):
            // solo queda el matiz sustantivo de ajuste por splits.
            formatColumns={{
                action_type: (value) =>
                    typeof value === 'string'
                        ? corporateActionTypeLabels(ti)[value] ?? value
                        : String(value ?? '—'),
                effective_date: (value) => f.formatMarketDate(value as string | null),
                description: (value, record) => dividendDescription(ti, f, record, value),
                ratio: (value) => f.formatNumber(value as number | string | null, { maximumFractionDigits: 4 }),
            }}
            emptyMessage={emptyMessage ?? (ticker ? ti('corporateActions.emptyForTicker', { ticker }) : ti('corporateActions.empty'))}
            pageSize={25}
            paginationLabel={ti('corporateActions.paginationLabel')}
            linkColumns={{ ticker: (record) => researchHrefFor(record) }}
            rowActions={(record, _index, replace) => {
                const actionId = recordActionId(record);
                // Dividendo declarado del proveedor: solo informativo, el cobro
                // se registra a mano en la cartera.
                if (record.action_type === 'dividend') {
                    return record.declared === false
                        ? <span className="text-xs text-amber-400/90">{ti('corporateActions.row.uncertainAmount')}</span>
                        : <span className="text-xs text-gray-500">{ti('corporateActions.row.fromProvider')}</span>;
                }
                if (isApplied(record)) {
                    return (
                        <span className="inline-flex items-center gap-1.5 text-xs text-gray-500">
                            <CheckCircle2 className="h-4 w-4 text-teal-400" />
                            {ti('corporateActions.row.applied')}
                        </span>
                    );
                }
                // Split anterior a tu primera operación: tus acciones ya se
                // compraron después, así que está reflejado y no se aplica.
                if (record.historical === true) {
                    return (
                        <span className="text-xs text-gray-500">{ti('corporateActions.row.historical')}</span>
                    );
                }
                // Empresa fuera de tu cartera: no hay posición ni operaciones que ajustar.
                if (record.no_position === true) {
                    return (
                        <span className="text-xs text-gray-500">{ti('corporateActions.row.noPosition')}</span>
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
