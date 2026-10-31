'use client';

import Link from 'next/link';
import { Crosshair, Landmark, PiggyBank, Target } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';
import { RecordDetail, RecordList, type DataRecord } from '@/components/data/RecordViews';
import { getPlan, getPlanContributions, getPlanDrift } from '@/lib/actions/plan.actions';
import PlanSetupDialog from '@/components/plan/PlanSetupDialog';
import ContributionSplitCard from '@/components/plan/ContributionSplitCard';
import PlanContributionDialog from '@/components/plan/PlanContributionDialog';
import DeleteContributionButton from '@/components/plan/DeleteContributionButton';
import type { ContributionSplit } from '@/lib/plan/contribution-split';
import { etiquetaSector } from '@/lib/labels';
import { useLocale, useFormat, useT } from '@/lib/i18n/client';

interface PlanViewProps {
    initialPlan: DataRecord | null;
    initialContributions: DataRecord[];
    initialDrift: DataRecord | null;
    /** Reparto de la aportación de este mes por nivel DCA (null = no disponible). */
    initialSplit?: ContributionSplit | null;
}

const BASE_HIDDEN_PLAN_KEYS = ['id', 'plan_exists', 'currency_contract_enabled', 'monthly_currency_recorded', 'monthly_contribution_currency', 'expected_basis', 'expected_conversion_complete'];
/** Campos que solo explican conversiones de divisa. */
const FX_DETAIL_KEYS = ['expected_contributions_converted_base', 'expected_missing_fx', 'expected_periods', 'actual_contributions_converted_base', 'contributions_complete', 'contributions_missing_fx'];

/**
 * Sin ninguna conversión pendiente (cuota en la divisa base o sin divisa, y
 * todas las aportaciones con tipo de cambio) los campos «convertidas (parcial
 * si…)», «cuotas sin tipo de cambio: —» o «cuotas previstas: N/D» repetían el
 * total o no decían nada: se ocultan. Si falta algún tipo, se muestran.
 */
export function planHiddenKeys(plan: Record<string, unknown>): string[] {
    const base = typeof plan.base_currency === 'string' ? plan.base_currency.toUpperCase() : null;
    const planCurrency = typeof plan.monthly_contribution_currency === 'string' && plan.monthly_contribution_currency
        ? plan.monthly_contribution_currency.toUpperCase()
        : null;
    const empty = (value: unknown) => !Array.isArray(value) || value.length === 0;
    const noFx = (planCurrency === null || planCurrency === base)
        && plan.contributions_complete !== false
        && empty(plan.contributions_missing_fx)
        && empty(plan.expected_missing_fx)
        && empty(plan.expected_periods);
    // «Plan configurado: Sí» es tautológico dentro de la propia tarjeta del plan.
    return noFx ? [...BASE_HIDDEN_PLAN_KEYS, ...FX_DETAIL_KEYS] : BASE_HIDDEN_PLAN_KEYS;
}

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
    const t = useT();
    const f = useFormat();
    const locale = useLocale();
    // Los sectores llegan en inglés del backend: en es-ES se traducen con
    // etiquetaSector; en en-US se muestran tal cual (ya llegan en inglés).
    const sector = (name: string): string => (locale === 'en' ? name : etiquetaSector(name));
    const cashLabel = t('plan.kind.cash');
    const tickerPrefix = `${t('plan.kind.ticker')}: `;
    const cashKey = `asset_class:${cashLabel}`;

    /** Etiquetas de las claves que devuelve GET /api/plan
     *  (investment_plan_service.plan_metrics). Sin ellas la tarjeta pintaba la
     *  clave cruda en mayúsculas: «PLAN_EXISTS», «MONTHLY_CONTRIBUTION»... */
    const PLAN_LABELS: Record<string, string> = {
        plan_exists: t('plan.planKeys.plan_exists'),
        id: t('plan.planKeys.id'),
        base_currency: t('plan.planKeys.base_currency'),
        monthly_contribution: t('plan.planKeys.monthly_contribution'),
        start_date: t('plan.planKeys.start_date'),
        horizon_years: t('plan.planKeys.horizon_years'),
        months_elapsed: t('plan.planKeys.months_elapsed'),
        expected_contributions_base: t('plan.planKeys.expected_contributions_base'),
        actual_contributions_base: t('plan.planKeys.actual_contributions_base'),
        actual_contributions_converted_base: t('plan.planKeys.actual_contributions_converted_base'),
        contributions_complete: t('plan.planKeys.contributions_complete'),
        contributions_missing_fx: t('plan.planKeys.contributions_missing_fx'),
        gap_base: t('plan.planKeys.gap_base'),
        on_track: t('plan.planKeys.on_track'),
        target_allocations: t('plan.planKeys.target_allocations'),
        monthly_contribution_currency: t('plan.planKeys.monthly_contribution_currency'),
        monthly_currency_recorded: t('plan.planKeys.monthly_currency_recorded'),
        currency_contract_enabled: t('plan.planKeys.currency_contract_enabled'),
        expected_basis: t('plan.planKeys.expected_basis'),
        expected_periods: t('plan.planKeys.expected_periods'),
        expected_contributions_converted_base: t('plan.planKeys.expected_contributions_converted_base'),
        expected_missing_fx: t('plan.planKeys.expected_missing_fx'),
        expected_conversion_complete: t('plan.planKeys.expected_conversion_complete'),
    };

    /** Claves de GET /api/plan/drift (investment_plan_service.drift_analysis). */
    const DRIFT_LABELS: Record<string, string> = {
        plan_exists: t('plan.driftKeys.plan_exists'),
        status: t('common.labels.status'),
        portfolio_value_base: t('plan.driftKeys.portfolio_value_base'),
        cash_base: t('plan.driftKeys.cash_base'),
        missing_fx: t('plan.driftKeys.missing_fx'),
        suggestions_blocked: t('plan.driftKeys.suggestions_blocked'),
        current_weights: t('plan.driftKeys.current_weights'),
        deviations: t('plan.driftKeys.deviations'),
        suggestions: t('plan.driftKeys.suggestions'),
        next_contribution: t('plan.driftKeys.next_contribution'),
        next_contribution_currency: t('plan.driftKeys.next_contribution_currency'),
        next_contribution_basis: t('plan.driftKeys.next_contribution_basis'),
    };

    /** Etiquetas de GET /api/plan/contributions. `external_id` no se declara en la
     *  respuesta (plan.list_contributions), así que salía siempre a «—». */
    const CONTRIBUTION_LABELS: Record<string, string> = {
        id: t('plan.contributionKeys.id'),
        date: t('common.labels.date'),
        amount: t('plan.contributionKeys.amount'),
        currency: t('plan.contributionKeys.currency'),
        note: t('plan.contributionKeys.note'),
    };

    const PLAN_KIND: Record<string, string> = { ticker: t('plan.kind.ticker'), sector: t('plan.kind.sector'), asset_class: t('plan.kind.assetClass') };
    /** Valores de `kind` que manda el drift en missing_fx (cash/position): no son
     *  tipos de objetivo (PLAN_KIND) y salían en inglés en la tarjeta de desviación. */
    const DRIFT_KIND: Record<string, string> = { cash: t('plan.kind.cash'), position: t('plan.kind.position') };
    const FIELD_LABELS: Record<string, string> = {
        kind: t('plan.fieldKeys.kind'), label: t('plan.fieldKeys.label'), target_pct: t('plan.fieldKeys.target_pct'), band_pct: t('plan.fieldKeys.band_pct'),
        direction: t('plan.fieldKeys.direction'), detail: t('plan.fieldKeys.detail'), within_band: t('plan.fieldKeys.within_band'), current_pct: t('plan.fieldKeys.current_pct'), deviation_pct: t('plan.fieldKeys.deviation_pct'), action: t('plan.fieldKeys.action'), amount_base: t('plan.fieldKeys.amount_base'),
        // Claves de missing_fx (drift y contributions_missing_fx): antes caían al
        // fallback y el usuario leía «quote currency», «as of» y «position» en crudo.
        quote_currency: t('plan.fieldKeys.quote_currency'), base_currency: t('plan.fieldKeys.base_currency'), as_of: t('plan.fieldKeys.as_of'), ticker: t('plan.fieldKeys.ticker'),
    };

    function planValue(value: unknown, currency?: string, weights = false): string {
        if (value == null) return t('common.na');
        if (Array.isArray(value)) return value.length ? value.map(item => planValue(item, currency, weights)).join('\n\n') : t('common.na');
        if (typeof value === 'object') {
            const record = value as DataRecord;
            // asset_class:Cash llega en inglés del contrato; en la cabecera se veía
            // «Clase de activo: Cash» (las claves ticker:/asset_class: ya traducen Caja).
            const heading = typeof record.kind === 'string' && typeof record.label === 'string'
                ? `${PLAN_KIND[record.kind] ?? record.kind}: ${record.label === 'Cash' ? cashLabel : sector(record.label)}` : null;
            const lines = Object.entries(value).filter(([key]) => !heading || (key !== 'kind' && key !== 'label')).map(([key, item]) => {
            // El detalle llega del backend con la etiqueta cruda («Technology está…»):
            // se sustituye por la misma etiqueta traducida que la cabecera.
            if (key === 'detail' && heading && typeof item === 'string' && typeof record.label === 'string' && item.startsWith(record.label)) {
                item = (record.label === 'Cash' ? cashLabel : sector(record.label)) + item.slice(record.label.length);
            }
            const text = (weights || key.endsWith('_pct') || key.startsWith('ticker:') || key.startsWith('asset_class:')) ? f.formatPercent(item as number, { fromRatio: false, digits: 2 })
                : key === 'amount_base' ? (currency ? f.formatMoney(item as number, currency) : t('common.na'))
                : key === 'kind' ? PLAN_KIND[String(item)] ?? DRIFT_KIND[String(item)] ?? String(item)
                : key === 'as_of' ? f.formatDate(item as string | null) : planValue(item, currency);
            return `${FIELD_LABELS[key] ?? sector(key.replace(/^ticker:/, tickerPrefix).replace(/^asset_class:Cash$/, cashKey).replaceAll('_', ' '))}: ${text}`;
        });
            return [heading, ...lines].filter(Boolean).join('\n');
        }
        if (typeof value === 'number') return f.formatNumber(value);
        if (typeof value === 'boolean') return value ? t('plan.values.yes') : t('plan.values.no');
        const text = String(value);
        const cleanText = text.replace(/\besta\b/g, 'está').replace(/([+-]?\d+\.\d+) puntos/g, (_all, number) => `${number.startsWith('+') ? '+' : ''}${f.formatNumber(Number(number), {maximumFractionDigits: 2})} puntos`);
        const statusLabels: Record<string, string> = {
            ok: t('plan.values.statusOk'),
            incomplete_fx: t('plan.values.statusIncompleteFx'),
            empty_portfolio: t('plan.values.statusEmptyPortfolio'),
            buy: t('plan.values.buy'),
            sell: t('plan.values.sell'),
        };
        return statusLabels[text] ?? sector(cleanText.replace(/^ticker:/, tickerPrefix).replace(/^asset_class:Cash$/, cashKey));
    }
    const planMoney = (value: unknown, record: DataRecord) =>
        typeof record.base_currency === 'string' ? f.formatMoney(value as number | string | null, record.base_currency) : t('common.na');
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
        if (recorded) return f.formatMoney(value as number | string | null, recorded);
        // Plan legacy sin divisa (contrato activo, o el backend marca monthly_currency_recorded=false):
        // importe crudo, sin simbolo inventado. Coherente con «Próxima aportación», que lee el mismo campo.
        if (record.currency_contract_enabled === true || record.monthly_currency_recorded === false) {
            return typeof value === 'number' ? `${f.formatNumber(value)} ${t('plan.values.currencyNotRegistered')}` : t('common.na');
        }
        return typeof record.base_currency === 'string'
            ? f.formatMoney(value as number | string | null, record.base_currency)
            : f.formatMoney(value as number | string | null, 'EUR');
    };
    /** next_contribution es el importe del plan en SU divisa (next_contribution_currency),
     *  nunca en base. Null = bloqueado (capability off con divisa distinta de la base). */
    const planNext = (value: unknown, record: DataRecord) =>
        typeof record.next_contribution_currency === 'string' && record.next_contribution_currency
            ? f.formatMoney(value as number | string | null, record.next_contribution_currency)
            : typeof value === 'number' ? `${f.formatNumber(value)} ${t('plan.values.currencyNotRegistered')}` : t('common.na');
    /** Resumen de cuotas previstas: «pendiente de vencimiento» no es un error ni un FX faltante. */
    const planExpectedPeriods = (value: unknown, record: DataRecord) => {
        // Contrato activo y divisa sin registrar: las cuotas no se pueden calcular, no es «0 cuotas».
        if (record.currency_contract_enabled === true && record.monthly_currency_recorded !== true) {
            return t('plan.values.periodsNotCalculable');
        }
        // Plan legacy: el backend no desglosa cuotas (lista vacía); «0 convertidas,
        // 0 pendientes» contradecía las «Aportaciones previstas» de arriba.
        if (!Array.isArray(value) || value.length === 0) return t('common.na');
        const count = (status: string) => value.filter((p) => p && typeof p === 'object' && (p as Record<string, unknown>).status === status).length;
        const parts = [t('plan.values.periodsConverted', { n: count('converted') }), t('plan.values.periodsPending', { n: count('pending_due_date') })];
        const missing = count('missing_rate');
        if (missing > 0) parts.push(t('plan.values.periodsMissingFx', { n: missing }));
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
            ? ` ${t('plan.values.expectedMissingFxRange', { first: f.formatMarketDate(first.due_date), last: f.formatMarketDate(last.due_date) })}` : '';
        return t('plan.values.expectedMissingFx', {
            count: rows.length,
            unit: rows.length === 1 ? t('plan.values.expectedMissingFxUnit') : t('plan.values.expectedMissingFxUnitPlural'),
            pair,
            range,
        });
    };
    /** Aportaciones registradas que no se pueden convertir a la divisa base: resumen legible,
     *  no «contribution id: 4 · quote currency: USD · as of: …». */
    const planContributionsMissingFx = (value: unknown) => {
        if (!Array.isArray(value) || value.length === 0) return '—';
        const rows = value.filter((r): r is Record<string, unknown> => !!r && typeof r === 'object');
        const pairs = [...new Set(rows
            .filter((r) => typeof r.quote_currency === 'string' && typeof r.base_currency === 'string')
            .map((r) => `${String(r.quote_currency).toUpperCase()}→${String(r.base_currency).toUpperCase()}`))];
        const dates = rows.map((r) => (typeof r.as_of === 'string' ? f.formatMarketDate(r.as_of) : null)).filter(Boolean);
        const shown = dates.length > 3 ? [...dates.slice(0, 3), t('plan.values.andMore', { n: dates.length - 3 })] : dates;
        return t('plan.values.contributionsMissingFx', {
            count: rows.length,
            unit: rows.length === 1 ? t('plan.values.contributionsMissingFxUnit') : t('plan.values.contributionsMissingFxUnitPlural'),
            pairs: pairs.length ? ` ${pairs.join(', ')}` : '',
            dates: shown.length ? ` (${shown.join(', ')})` : '',
        });
    };
    const PLAN_FORMAT = {contributions_missing_fx: planContributionsMissingFx, start_date: (value: unknown) => f.formatMarketDate(value as string), monthly_contribution: planMonthly, next_contribution: planNext, expected_periods: planExpectedPeriods, expected_missing_fx: planExpectedMissingFx, ...Object.fromEntries(['expected_contributions_base', 'expected_contributions_converted_base', 'actual_contributions_base', 'actual_contributions_converted_base', 'gap_base', 'portfolio_value_base', 'cash_base'].map(key => [key, planMoney]))};
    const DETAIL_FORMAT = Object.fromEntries(['target_allocations', 'current_weights', 'deviations', 'suggestions', 'missing_fx', 'status'].map(key => [key, (value: unknown, record: DataRecord) => planValue(value, typeof record.base_currency === 'string' ? record.base_currency : undefined, key === 'current_weights')]));

    const tickers = extractPlanTickers(initialDrift, initialPlan);

    /** Enlace de navegación cruzada Plan → Cartera: la desviación y los pesos del
     *  plan se calculan SOBRE la cartera, así que cada estado (con datos o vacío)
     *  ofrece el salto a su fuente en vez de quedarse en texto muerto. */
    const linkCartera = (
        <Link
            href="/portfolio"
            className="inline-flex min-h-[44px] items-center rounded-lg border border-teal-700/60 px-3 text-sm font-medium text-teal-300 transition hover:border-teal-500 hover:text-teal-200"
        >
            {t('plan.viewPortfolio')}
        </Link>
    );

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
                description={t('plan.emptyGuide')}
                action={<PlanSetupDialog />}
            />
        );
    }

    // Divisa por defecto de una aportación: la registrada en el plan; si no, la base.
    const planCurrency = typeof initialPlan.monthly_contribution_currency === 'string' && initialPlan.monthly_contribution_currency
        ? initialPlan.monthly_contribution_currency
        : typeof initialPlan.base_currency === 'string' ? initialPlan.base_currency : 'EUR';
    const contributionDialog = (
        <PlanContributionDialog
            defaultAmount={typeof initialPlan.monthly_contribution === 'number' ? initialPlan.monthly_contribution : null}
            defaultCurrency={planCurrency}
        />
    );

    return (
        <div className="grid gap-6">
            <RecordDetail
                title={t('plan.sections.goalTitle')}
                titleAs="h2"
                description={t('plan.sections.goalDescription')}
                icon={<Target className="h-5 w-5 text-teal-400" />}
                record={initialPlan}
                fetchRecord={getPlan}
                columnLabels={PLAN_LABELS}
                hiddenKeys={planHiddenKeys(initialPlan)}
                formatColumns={{...PLAN_FORMAT, ...DETAIL_FORMAT}}
                maxKeys={20}
                emptyMessage={t('plan.empty')}
                emptyAction={<PlanSetupDialog />}
                actions={initialPlan?.plan_exists === true ? <PlanSetupDialog triggerLabel={t('plan.setup.edit')} initial={initialPlan} /> : undefined}
            />

            {initialPlan?.plan_exists === true ? <ContributionSplitCard split={initialSplit} /> : null}

            <Card className="rounded-lg border border-gray-700 bg-gray-800/50">
                <CardHeader className="border-b border-gray-700/50 pb-4">
                    <div className="flex items-center gap-3">
                        <Crosshair className="h-5 w-5 text-teal-400" />
                        <div>
                            <CardTitle as="h2" className="text-lg font-semibold text-gray-100">
                                {t('plan.sections.positionsTitle')}
                            </CardTitle>
                            <CardDescription className="mt-0.5 text-sm text-gray-500">
                                {t('plan.sections.positionsDescription')}
                            </CardDescription>
                        </div>
                    </div>
                </CardHeader>
                <CardContent className="pt-4">
                    {tickers.length === 0 ? (
                        <div className="flex flex-col items-center gap-3 py-6">
                            <p className="text-center text-sm text-gray-500">
                                {t('plan.sections.positionsEmpty')}
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
                title={t('plan.sections.driftTitle')}
                titleAs="h2"
                description={t('plan.sections.driftDescription')}
                icon={<PiggyBank className="h-5 w-5 text-teal-400" />}
                record={initialDrift}
                fetchRecord={getPlanDrift}
                columnLabels={DRIFT_LABELS}
                hiddenKeys={['base_currency', 'next_contribution_currency', 'next_contribution_basis']}
                formatColumns={{...PLAN_FORMAT, ...DETAIL_FORMAT}}
                maxKeys={24}
                emptyMessage={t('plan.sections.driftEmpty')}
                emptyAction={linkCartera}
                actions={linkCartera}
            />

            <RecordList
                // RecordList guarda sus filas en estado local: al alta/baja,
                // router.refresh() trae props nuevas y la clave fuerza a pintarlas.
                key={initialContributions.map((row) => String(row.id ?? '')).join(',')}
                title={t('plan.sections.contributionsTitle')}
                titleAs="h2"
                description={t('plan.sections.contributionsDescription')}
                icon={<Landmark className="h-5 w-5 text-teal-400" />}
                records={initialContributions}
                fetchRecords={getPlanContributions}
                columns={['date', 'amount', 'currency', 'note']}
                columnLabels={CONTRIBUTION_LABELS}
                formatColumns={{
                    date: (value) => f.formatMarketDate(value as string),
                    currency: (value) => (typeof value === 'string' && value ? value.toUpperCase() : t('common.na')),
                    amount: (value, record) =>
                        f.formatMoney(value as number | string | null, typeof record.currency === 'string' ? record.currency : 'EUR'),
                }}
                emptyMessage={t('plan.sections.contributionsEmpty')}
                emptyAction={contributionDialog}
                footer={initialContributions.length > 0 ? <div className="flex justify-end">{contributionDialog}</div> : undefined}
                rowActions={(record) => typeof record.id === 'number' ? (
                    <DeleteContributionButton
                        contributionId={record.id}
                        label={`${f.formatMarketDate(String(record.date ?? ''))} · ${f.formatMoney(record.amount as number | string | null, typeof record.currency === 'string' && record.currency ? record.currency.toUpperCase() : 'EUR')}`}
                    />
                ) : null}
            />
        </div>
    );
}
