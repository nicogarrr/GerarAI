'use client';

import Link from 'next/link';
import { Crosshair, Landmark, PiggyBank, Target } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';
import { RecordDetail, RecordList, type DataRecord } from '@/components/data/RecordViews';
import { getPlan, getPlanContributions, getPlanDrift } from '@/lib/actions/plan.actions';
import PlanSetupDialog from '@/components/plan/PlanSetupDialog';
import ContributionSplitCard from '@/components/plan/ContributionSplitCard';
import type { ContributionSplit } from '@/lib/plan/contribution-split';
import { formatDate, formatMoney, formatNumber, formatPercent, formatMarketDate, NA } from '@/lib/format';
import { etiquetaSector } from '@/lib/labels';
import { t } from '@/lib/i18n/t';

interface PlanViewProps {
    initialPlan: DataRecord | null;
    initialContributions: DataRecord[];
    initialDrift: DataRecord | null;
    /** Reparto de la aportación de este mes por nivel DCA (null = no disponible). */
    initialSplit?: ContributionSplit | null;
}

/** Etiquetas de las claves que devuelve GET /api/plan
 *  (investment_plan_service.plan_metrics). Sin ellas la tarjeta pintaba la
 *  clave cruda en mayúsculas: «PLAN_EXISTS», «MONTHLY_CONTRIBUTION»... */
const PLAN_LABELS: Record<string, string> = {
    plan_exists: 'Plan configurado',
    id: 'Identificador',
    base_currency: 'Divisa base',
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
    monthly_contribution_currency: 'Divisa de la aportación',
    monthly_currency_recorded: 'Divisa registrada',
    currency_contract_enabled: 'Contrato de divisa activo',
    expected_basis: 'Base del cálculo previsto',
    expected_periods: 'Cuotas previstas',
    expected_contributions_converted_base: 'Aportaciones previstas convertidas (parcial si faltan tipos de cambio)',
    expected_missing_fx: 'Cuotas sin tipo de cambio',
    expected_conversion_complete: 'Conversión prevista completa',
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
    next_contribution_currency: 'Divisa de la próxima aportación',
    next_contribution_basis: 'Base de la próxima aportación',
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

/** Enlace de navegación cruzada Plan → Cartera: la desviación y los pesos del
 *  plan se calculan SOBRE la cartera, así que cada estado (con datos o vacío)
 *  ofrece el salto a su fuente en vez de quedarse en texto muerto. */
const linkCartera = (
    <Link
        href="/portfolio"
        className="inline-flex min-h-[44px] items-center rounded-lg border border-teal-700/60 px-3 text-sm font-medium text-teal-300 transition hover:border-teal-500 hover:text-teal-200"
    >
        Ver tu cartera
    </Link>
);
const FIELD_LABELS: Record<string, string> = {
    kind: 'Tipo', label: 'Objetivo', target_pct: 'Peso objetivo', band_pct: 'Banda de tolerancia',
    direction: 'Operación', detail: 'Detalle', within_band: 'Dentro de la banda', current_pct: 'Peso actual', deviation_pct: 'Desviación', action: 'Acción', amount_base: 'Importe',
    // Claves de missing_fx (drift y contributions_missing_fx): antes caían al
    // fallback y el usuario leía «quote currency», «as of» y «position» en crudo.
    quote_currency: 'Divisa de cotización', base_currency: 'Divisa base', as_of: 'Fecha', ticker: 'Ticker',
};
/** Valores de `kind` que manda el drift en missing_fx (cash/position): no son
 *  tipos de objetivo (PLAN_KIND) y salían en inglés en la tarjeta de desviación. */
const DRIFT_KIND: Record<string, string> = { cash: 'Caja', position: 'Posición' };
function planValue(value: unknown, currency?: string, weights = false): string {
    if (value == null) return NA;
    if (Array.isArray(value)) return value.length ? value.map(item => planValue(item, currency, weights)).join('\n\n') : NA;
    if (typeof value === 'object') {
        const record = value as DataRecord;
        // asset_class:Cash llega en inglés del contrato; en la cabecera se veía
        // «Clase de activo: Cash» (las claves ticker:/asset_class: ya traducen Caja).
        const heading = typeof record.kind === 'string' && typeof record.label === 'string'
            ? `${PLAN_KIND[record.kind] ?? record.kind}: ${record.label === 'Cash' ? 'Caja' : etiquetaSector(record.label)}` : null;
        const lines = Object.entries(value).filter(([key]) => !heading || (key !== 'kind' && key !== 'label')).map(([key, item]) => {
        // El detalle llega del backend con la etiqueta cruda («Technology está…»):
        // se sustituye por la misma etiqueta traducida que la cabecera.
        if (key === 'detail' && heading && typeof item === 'string' && typeof record.label === 'string' && item.startsWith(record.label)) {
            item = (record.label === 'Cash' ? 'Caja' : etiquetaSector(record.label)) + item.slice(record.label.length);
        }
        const text = (weights || key.endsWith('_pct') || key.startsWith('ticker:') || key.startsWith('asset_class:')) ? formatPercent(item as number, { fromRatio: false, digits: 2 })
            : key === 'amount_base' ? (currency ? formatMoney(item as number, currency) : NA)
            : key === 'kind' ? PLAN_KIND[String(item)] ?? DRIFT_KIND[String(item)] ?? String(item)
            : key === 'as_of' ? formatDate(item as string | null) : planValue(item, currency);
        return `${FIELD_LABELS[key] ?? etiquetaSector(key.replace(/^ticker:/, 'Acción: ').replace(/^asset_class:Cash$/, 'Caja').replaceAll('_', ' '))}: ${text}`;
    });
        return [heading, ...lines].filter(Boolean).join('\n');
    }
    if (typeof value === 'number') return formatNumber(value);
    if (typeof value === 'boolean') return value ? 'Sí' : 'No';
    const text = String(value);
    const cleanText = text.replace(/\besta\b/g, 'está').replace(/([+-]?\d+\.\d+) puntos/g, (_all, number) => `${number.startsWith('+') ? '+' : ''}${formatNumber(Number(number), {maximumFractionDigits: 2})} puntos`);
    return ({ok: 'Completo', incomplete_fx: 'Faltan tipos de cambio', empty_portfolio: 'Cartera vacía: nada que reequilibrar todavía', buy: 'Comprar', sell: 'Vender'} as Record<string, string>)[text] ?? etiquetaSector(cleanText.replace(/^ticker:/, 'Acción: ').replace(/^asset_class:Cash$/, 'Caja'));
}
const planMoney = (value: unknown, record: DataRecord) =>
    typeof record.base_currency === 'string' ? formatMoney(value as number | string | null, record.base_currency) : NA;
/** monthly_contribution es INPUT crudo del usuario (el diálogo lo captura en €,
 *  PlanSetupDialog), no un importe convertido a divisa base: sin cartera no hay
 *  base_currency y planMoney lo pintaba N/D escondiendo el dato. Sin cartera se
 *  muestra en EUR, la divisa en la que el usuario lo introdujo; con cartera se
 *  mantiene la divisa base como antes. Los campos *_base sí necesitan FX y su
 *  N/D sin cartera es honesto. */
const planMonthly = (value: unknown, record: DataRecord) => {
    // Divisa registrada con el plan: es la verdad del importe, con o sin cartera.
    const recorded = typeof record.monthly_contribution_currency === 'string' && record.monthly_contribution_currency
        ? record.monthly_contribution_currency
        : null;
    if (recorded) return formatMoney(value as number | string | null, recorded);
    // Plan legacy sin divisa (contrato activo, o el backend marca monthly_currency_recorded=false):
    // importe crudo, sin simbolo inventado. Coherente con «Próxima aportación», que lee el mismo campo.
    if (record.currency_contract_enabled === true || record.monthly_currency_recorded === false) {
        return typeof value === 'number' ? `${formatNumber(value)} (divisa no registrada)` : NA;
    }
    return typeof record.base_currency === 'string'
        ? formatMoney(value as number | string | null, record.base_currency)
        : formatMoney(value as number | string | null, 'EUR');
};
/** next_contribution es el importe del plan en SU divisa (next_contribution_currency),
 *  nunca en base. Null = bloqueado (capability off con divisa distinta de la base). */
const planNext = (value: unknown, record: DataRecord) =>
    typeof record.next_contribution_currency === 'string' && record.next_contribution_currency
        ? formatMoney(value as number | string | null, record.next_contribution_currency)
        : typeof value === 'number' ? `${formatNumber(value)} (divisa no registrada)` : NA;
/** Resumen de cuotas previstas: «pendiente de vencimiento» no es un error ni un FX faltante. */
const planExpectedPeriods = (value: unknown, record: DataRecord) => {
    // Contrato activo y divisa sin registrar: las cuotas no se pueden calcular, no es «0 cuotas».
    if (record.currency_contract_enabled === true && record.monthly_currency_recorded !== true) {
        return 'No calculables: divisa no registrada';
    }
    // Plan legacy: el backend no desglosa cuotas (lista vacía); «0 convertidas,
    // 0 pendientes» contradecía las «Aportaciones previstas» de arriba.
    if (!Array.isArray(value) || value.length === 0) return NA;
    const count = (status: string) => value.filter((p) => p && typeof p === 'object' && (p as Record<string, unknown>).status === status).length;
    const parts = [`${count('converted')} convertidas`, `${count('pending_due_date')} pendientes de vencimiento`];
    const missing = count('missing_rate');
    if (missing > 0) parts.push(`${missing} sin tipo de cambio`);
    return parts.join(', ');
};
/** Cuotas vencidas sin tipo de cambio en o antes de su fecha: resumen legible, no claves crudas. */
const planExpectedMissingFx = (value: unknown) => {
    if (!Array.isArray(value) || value.length === 0) return '—';
    const rows = value.filter((r): r is Record<string, unknown> => !!r && typeof r === 'object');
    const first = rows[0] ?? {};
    const last = rows[rows.length - 1] ?? {};
    const pair = typeof first.quote_currency === 'string' && typeof first.base_currency === 'string' ? ` ${first.quote_currency}→${first.base_currency}` : '';
    const range = typeof first.due_date === 'string' && typeof last.due_date === 'string'
        ? ` (vencidas del ${formatMarketDate(first.due_date)} al ${formatMarketDate(last.due_date)})` : '';
    return `${rows.length} ${rows.length === 1 ? 'cuota' : 'cuotas'} sin tipo de cambio${pair} en o antes del vencimiento${range}`;
};
/** Aportaciones registradas que no se pueden convertir a la divisa base: resumen legible,
 *  no «contribution id: 4 · quote currency: USD · as of: …». */
const planContributionsMissingFx = (value: unknown) => {
    if (!Array.isArray(value) || value.length === 0) return '—';
    const rows = value.filter((r): r is Record<string, unknown> => !!r && typeof r === 'object');
    const pairs = [...new Set(rows
        .filter((r) => typeof r.quote_currency === 'string' && typeof r.base_currency === 'string')
        .map((r) => `${String(r.quote_currency).toUpperCase()}→${String(r.base_currency).toUpperCase()}`))];
    const dates = rows.map((r) => (typeof r.as_of === 'string' ? formatMarketDate(r.as_of) : null)).filter(Boolean);
    const shown = dates.length > 3 ? [...dates.slice(0, 3), `y ${dates.length - 3} más`] : dates;
    return `${rows.length} ${rows.length === 1 ? 'aportación' : 'aportaciones'} sin tipo de cambio${pairs.length ? ` ${pairs.join(', ')}` : ''}${shown.length ? ` (${shown.join(', ')})` : ''}`;
};
const PLAN_FORMAT = {contributions_missing_fx: planContributionsMissingFx, start_date: (value: unknown) => formatMarketDate(value as string), monthly_contribution: planMonthly, next_contribution: planNext, expected_periods: planExpectedPeriods, expected_missing_fx: planExpectedMissingFx, ...Object.fromEntries(['expected_contributions_base', 'expected_contributions_converted_base', 'actual_contributions_base', 'actual_contributions_converted_base', 'gap_base', 'portfolio_value_base', 'cash_base'].map(key => [key, planMoney]))};
const DETAIL_FORMAT = Object.fromEntries(['target_allocations', 'current_weights', 'deviations', 'suggestions', 'missing_fx', 'status'].map(key => [key, (value: unknown, record: DataRecord) => planValue(value, typeof record.base_currency === 'string' ? record.base_currency : undefined, key === 'current_weights')]));

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

export default function PlanView({ initialPlan, initialContributions, initialDrift, initialSplit = null }: PlanViewProps) {
    const tickers = extractPlanTickers(initialDrift, initialPlan);

    // Sin plan la página es UNA guía de creación, no cuatro secciones que
    // repiten cada una su «sin datos» («No hay plan configurado», «sin
    // posiciones», «sin desviación», «sin aportaciones»): superficie a medias
    // medida en prod (auditoría 29-oct-2026) contra la regla «nada a medias».
    // Se guía la creación en vez de ocultar la pestaña porque escondiéndola
    // el alta quedaría indescubrible. `getPlan` normaliza {plan_exists:false}
    // a null y un backend caído sale antes por BackendOffline, así que
    // null aquí significa exactamente «todavía no tienes plan».
    if (initialPlan === null) {
        return (
            <EmptyState
                icon={Target}
                title={t('plan.empty')}
                description="Configura tu objetivo a largo plazo: aportación mensual, horizonte y asignación por empresa, sector o clase de activo. Con el plan creado, aquí verás las aportaciones y la desviación de tu cartera frente a ese objetivo."
                action={<PlanSetupDialog />}
            />
        );
    }

    return (
        <div className="grid gap-6">
            <RecordDetail
                title="Objetivo y asignación"
                titleAs="h2"
                description="Objetivo a largo plazo, aportación mensual y asignación objetivo"
                icon={<Target className="h-5 w-5 text-teal-400" />}
                record={initialPlan}
                fetchRecord={getPlan}
                columnLabels={PLAN_LABELS}
                hiddenKeys={['id', 'currency_contract_enabled', 'monthly_currency_recorded', 'monthly_contribution_currency', 'expected_basis', 'expected_conversion_complete']}
                formatColumns={{...PLAN_FORMAT, ...DETAIL_FORMAT}}
                maxKeys={20}
                emptyMessage={t('plan.empty')}
                emptyAction={<PlanSetupDialog />}
                actions={initialPlan?.plan_exists === true ? <PlanSetupDialog triggerLabel="Editar plan" initial={initialPlan} /> : undefined}
            />

            {initialPlan?.plan_exists === true ? <ContributionSplitCard split={initialSplit} /> : null}

            <Card className="rounded-lg border border-gray-700 bg-gray-800/50">
                <CardHeader className="border-b border-gray-700/50 pb-4">
                    <div className="flex items-center gap-3">
                        <Crosshair className="h-5 w-5 text-teal-400" />
                        <div>
                            <CardTitle as="h2" className="text-lg font-semibold text-gray-100">
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
                        <div className="flex flex-col items-center gap-3 py-6">
                            <p className="text-center text-sm text-gray-500">
                                El plan no tiene posiciones por ticker todavía.
                            </p>
                            {linkCartera}
                        </div>
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
                titleAs="h2"
                description="Desviación de la cartera actual frente a la asignación objetivo"
                icon={<PiggyBank className="h-5 w-5 text-teal-400" />}
                record={initialDrift}
                fetchRecord={getPlanDrift}
                columnLabels={DRIFT_LABELS}
                hiddenKeys={['base_currency', 'next_contribution_currency', 'next_contribution_basis']}
                formatColumns={{...PLAN_FORMAT, ...DETAIL_FORMAT}}
                maxKeys={24}
                emptyMessage="Sin datos de desviación disponibles."
                emptyAction={linkCartera}
                actions={linkCartera}
            />

            <RecordList
                title="Aportaciones"
                titleAs="h2"
                description="Historial de contribuciones al plan"
                icon={<Landmark className="h-5 w-5 text-teal-400" />}
                records={initialContributions}
                fetchRecords={getPlanContributions}
                columns={['date', 'amount', 'currency', 'note']}
                columnLabels={CONTRIBUTION_LABELS}
                formatColumns={{
                    date: (value) => formatMarketDate(value as string),
                    currency: (value) => (typeof value === 'string' && value ? value.toUpperCase() : NA),
                    amount: (value, record) =>
                        formatMoney(value as number | string | null, typeof record.currency === 'string' ? record.currency : 'EUR'),
                }}
                emptyMessage="Todavía no has registrado aportaciones a tu plan."
            />
        </div>
    );
}
