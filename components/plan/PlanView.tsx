'use client';

import Link from 'next/link';
import { Crosshair, Landmark, PiggyBank, Target } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { RecordDetail, RecordList, type DataRecord } from '@/components/data/RecordViews';
import { getPlan, getPlanContributions, getPlanDrift } from '@/lib/actions/plan.actions';
import PlanSetupDialog from '@/components/plan/PlanSetupDialog';
import { formatMoney, formatNumber, formatPercent, NA } from '@/lib/format';
import { t } from '@/lib/i18n/t';

interface PlanViewProps {
    initialPlan: DataRecord | null;
    initialContributions: DataRecord[];
    initialDrift: DataRecord | null;
}

/** Etiquetas de las claves que devuelve GET /api/plan
 *  (investment_plan_service.plan_metrics). Sin ellas la tarjeta pintaba la
 *  clave cruda en mayúsculas: «PLAN_EXISTS», «MONTHLY_CONTRIBUTION»... */
const PLAN_LABELS: Record<string, string> = {
    plan_exists: 'Plan configurado',
    id: 'Identificador',
    monthly_contribution: 'Aportación mensual',
    start_date: 'Fecha de inicio',
    horizon_years: 'Horizonte (años)',
    months_elapsed: 'Meses transcurridos',
    expected_contributions_base: 'Aportaciones previstas',
    actual_contributions_base: 'Aportaciones reales (solo si todas tienen tipo de cambio)',
    actual_contributions_converted_base: 'Aportaciones convertidas (parcial si faltan tipos de cambio)',
    contributions_complete: 'Aportaciones completas en divisa base',
    contributions_missing_fx: 'Aportaciones sin tipo de cambio',
    gap_base: 'Desviación',
    on_track: 'En camino',
    target_allocations: 'Asignación objetivo',
};

/** Claves de GET /api/plan/drift (investment_plan_service.drift_analysis). */
const DRIFT_LABELS: Record<string, string> = {
    plan_exists: 'Plan configurado',
    status: t('common.labels.status'),
    portfolio_value_base: 'Valor de la cartera',
    cash_base: 'Caja',
    missing_fx: 'Sin tipo de cambio para',
    suggestions_blocked: 'Sugerencias bloqueadas (cobertura parcial)',
    current_weights: 'Pesos actuales',
    deviations: 'Desviaciones',
    suggestions: 'Sugerencias',
    next_contribution: 'Próxima aportación',
};

/** Etiquetas de GET /api/plan/contributions. `external_id` no se declara en la
 *  respuesta (plan.list_contributions), así que salía siempre a «—». */
const CONTRIBUTION_LABELS: Record<string, string> = {
    id: 'Identificador',
    date: t('common.labels.date'),
    amount: 'Importe',
    currency: 'Divisa',
    note: 'Nota',
};

const PLAN_KIND: Record<string, string> = { ticker: 'Acción', sector: 'Sector', asset_class: 'Clase de activo' };
const FIELD_LABELS: Record<string, string> = {
    kind: 'Tipo', label: 'Objetivo', target_pct: 'Peso objetivo', band_pct: 'Banda de tolerancia',
    current_pct: 'Peso actual', deviation_pct: 'Desviación', action: 'Acción', amount_base: 'Importe',
};
function planValue(value: unknown): string {
    if (value == null) return NA;
    if (Array.isArray(value)) return value.length ? value.map(planValue).join(' · ') : NA;
    if (typeof value === 'object') return Object.entries(value).map(([key, item]) => {
        const text = (key.endsWith('_pct') || key.startsWith('ticker:') || key.startsWith('asset_class:')) ? formatPercent(item as number, { fromRatio: false, digits: 2 })
            : key === 'kind' ? PLAN_KIND[String(item)] ?? String(item) : planValue(item);
        return `${FIELD_LABELS[key] ?? key.replace(/^ticker:/, 'Acción: ').replace(/^asset_class:Cash$/, 'Caja').replaceAll('_', ' ')}: ${text}`;
    }).join(' · ');
    if (typeof value === 'number') return formatNumber(value);
    if (typeof value === 'boolean') return value ? 'Sí' : 'No';
    const text = String(value);
    return ({ok: 'Completo', incomplete_fx: 'Faltan tipos de cambio', buy: 'Comprar', sell: 'Vender'} as Record<string, string>)[text] ?? text.replace(/^ticker:/, 'Acción: ').replace(/^asset_class:Cash$/, 'Caja');
}
const planMoney = (value: unknown, record: DataRecord) =>
    typeof record.base_currency === 'string' ? formatMoney(value as number | string | null, record.base_currency) : NA;
const PLAN_FORMAT = Object.fromEntries(['monthly_contribution', 'expected_contributions_base', 'actual_contributions_base', 'actual_contributions_converted_base', 'gap_base', 'next_contribution', 'portfolio_value_base', 'cash_base'].map(key => [key, planMoney]));
const DETAIL_FORMAT = Object.fromEntries(['target_allocations', 'current_weights', 'deviations', 'suggestions', 'missing_fx', 'status'].map(key => [key, planValue]));

/** Extrae tickers del drift (current_weights "ticker:XXX", deviations kind ticker) y del plan (targets kind ticker) */
function extractPlanTickers(drift: DataRecord | null, plan: DataRecord | null): string[] {
    const found = new Set<string>();

    const weights = drift?.current_weights;
    if (weights !== null && typeof weights === 'object' && !Array.isArray(weights)) {
        for (const key of Object.keys(weights)) {
            const match = /^ticker:(.+)$/i.exec(key);
            if (match) found.add(match[1].trim().toUpperCase());
        }
    }

    const collectTickerLabels = (items: unknown) => {
        if (!Array.isArray(items)) return;
        for (const item of items) {
            if (item === null || typeof item !== 'object' || Array.isArray(item)) continue;
            const record = item as DataRecord;
            if (record.kind === 'ticker' && typeof record.label === 'string' && record.label.trim()) {
                found.add(record.label.trim().toUpperCase());
            }
        }
    };
    collectTickerLabels(drift?.deviations);
    collectTickerLabels(drift?.suggestions);
    collectTickerLabels(plan?.target_allocations);

    return [...found].filter(Boolean).sort();
}

export default function PlanView({ initialPlan, initialContributions, initialDrift }: PlanViewProps) {
    const tickers = extractPlanTickers(initialDrift, initialPlan);

    return (
        <div className="grid gap-6">
            <RecordDetail
                title="Objetivo y asignación"
                description="Objetivo a largo plazo, aportación mensual y asignación objetivo"
                icon={<Target className="h-5 w-5 text-teal-400" />}
                record={initialPlan}
                fetchRecord={getPlan}
                columnLabels={PLAN_LABELS}
                hiddenKeys={['id', 'base_currency']}
                formatColumns={{...PLAN_FORMAT, ...DETAIL_FORMAT}}
                maxKeys={20}
                emptyMessage={t('plan.empty')}
                emptyAction={<PlanSetupDialog />}
                actions={initialPlan?.plan_exists === true ? <PlanSetupDialog triggerLabel="Editar plan" initial={initialPlan} /> : undefined}
            />

            <Card className="rounded-lg border border-gray-700 bg-gray-800/50">
                <CardHeader className="border-b border-gray-700/50 pb-4">
                    <div className="flex items-center gap-3">
                        <Crosshair className="h-5 w-5 text-teal-400" />
                        <div>
                            <CardTitle className="text-lg font-semibold text-gray-100">
                                Posiciones del plan
                            </CardTitle>
                            <CardDescription className="mt-0.5 text-sm text-gray-500">
                                Empresas con objetivo o peso actual
                            </CardDescription>
                        </div>
                    </div>
                </CardHeader>
                <CardContent className="pt-4">
                    {tickers.length === 0 ? (
                        <p className="py-6 text-center text-sm text-gray-500">
                            El plan no tiene posiciones por ticker todavía.
                        </p>
                    ) : (
                        <div className="flex flex-wrap gap-2">
                            {tickers.map((ticker) => (
                                <Link
                                    key={ticker}
                                    href={`/research/${encodeURIComponent(ticker)}`}
                                    className="rounded-lg border border-gray-700 px-3 py-1.5 font-mono text-sm font-semibold text-teal-300 transition hover:border-teal-700 hover:text-teal-200"
                                >
                                    {ticker}
                                </Link>
                            ))}
                        </div>
                    )}
                </CardContent>
            </Card>

            <RecordDetail
                title="Desviación de la cartera"
                description="Desviación de la cartera actual frente a la asignación objetivo"
                icon={<PiggyBank className="h-5 w-5 text-teal-400" />}
                record={initialDrift}
                fetchRecord={getPlanDrift}
                columnLabels={DRIFT_LABELS}
                hiddenKeys={['base_currency']}
                formatColumns={{...PLAN_FORMAT, ...DETAIL_FORMAT}}
                maxKeys={24}
                emptyMessage="Sin datos de desviación disponibles."
            />

            <RecordList
                title="Aportaciones"
                description="Historial de contribuciones al plan"
                icon={<Landmark className="h-5 w-5 text-teal-400" />}
                records={initialContributions}
                fetchRecords={getPlanContributions}
                columns={['date', 'amount', 'currency', 'note']}
                columnLabels={CONTRIBUTION_LABELS}
                formatColumns={{
                    amount: (value, record) =>
                        formatMoney(value as number | string | null, typeof record.currency === 'string' ? record.currency : 'EUR'),
                }}
                emptyMessage="Todavía no has registrado aportaciones a tu plan."
            />
        </div>
    );
}
