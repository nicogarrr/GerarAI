'use client';

import Link from 'next/link';
import { useState } from 'react';
import { Briefcase, Gauge } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { RecordDetail, formatRecordValue, type DataRecord } from '@/components/data/RecordViews';
import { etiquetaFactor, etiquetaSector, etiquetaSeveridad } from '@/lib/labels';
import { useT, useFormat } from '@/lib/i18n/client';
import type { TranslateFn as TFunction } from '@/lib/i18n/translate';
import type { Formatters } from '@/lib/format';
import { sourceDisplay } from '@/lib/research/source-display';
import { getRiskDashboard } from '@/lib/actions/risk.actions';

interface RiskDashboardViewProps {
    initialDashboard: DataRecord | null;
}

function extractPositions(dashboard: DataRecord | null): DataRecord[] {
    if (!dashboard) return [];
    const raw = dashboard.positions;
    if (!Array.isArray(raw)) return [];
    return raw.filter(
        (item): item is DataRecord =>
            item !== null && typeof item === 'object' && !Array.isArray(item),
    );
}

function extractAlerts(dashboard: DataRecord | null): DataRecord[] {
    if (!dashboard) return [];
    const raw = dashboard.alerts;
    if (!Array.isArray(raw)) return [];
    return raw.filter(
        (item): item is DataRecord =>
            item !== null && typeof item === 'object' && !Array.isArray(item),
    );
}

/**
 * Explicación didáctica del umbral que dispara cada alerta. El motor solo
 * aplica reglas de concentración y liquidez (portfolio_risk.py): sin VaR ni
 * drawdown, y aquí se dice junto a cada alerta.
 */
function thresholdExplanation(t: TFunction, alert: DataRecord): string {
    const threshold = alert.threshold;
    if (threshold === 0.2) {
        return t('risk.thresholds.t20');
    }
    if (threshold === 0.1) {
        return t('risk.thresholds.t10');
    }
    if (threshold === 0) {
        return t('risk.thresholds.t0');
    }
    return t('risk.thresholds.generic');
}

/** Resumen sin arrays anidados (positions/alerts se muestran en su propia tabla) */
function headlineRecord(dashboard: DataRecord | null): DataRecord | null {
    if (!dashboard) return null;
    const { positions: _positions, alerts: _alerts, ...rest } = dashboard;
    void _positions;
    void _alerts;
    return rest;
}

const RISK_LABEL_KEYS: Record<string, string> = {
    total_value: 'risk.labels.totalValue',
    equity_value: 'risk.labels.equityValue',
    cash: 'risk.labels.cash',
    top_1_weight: 'risk.labels.top1Weight',
    top_5_weight: 'risk.labels.top5Weight',
    weight_basis: 'risk.labels.weightBasis',
    cash_assets_base: 'risk.labels.cashAssetsBase',
    margin_debt_base: 'risk.labels.marginDebtBase',
    sector_exposure: 'risk.labels.sectorExposure',
    factor_exposure: 'risk.labels.factorExposure',
    status: 'risk.labels.status',
    base_currency: 'risk.labels.baseCurrency',
    cash_native: 'risk.labels.cashNative',
    missing_fx: 'risk.labels.missingFx',
    data_as_of: 'risk.labels.dataAsOf',
    provenance: 'risk.labels.provenance',
    cash_as_of: 'risk.labels.cashAsOf',
    fx_rates: 'risk.labels.fxRates',
    valuation_dates_differ: 'risk.labels.valuationDatesDiffer',
    valuation_hold: 'risk.labels.valuationHold',
};

function riskStatusLabels(t: TFunction): Record<string, string> {
    return {
        ok: t('risk.status.ok'),
        incomplete_fx: t('risk.status.incompleteFx'),
        insufficient_data: t('risk.status.insufficientData'),
        incomplete_valuation: t('risk.status.incompleteValuation'),
    };
}

function humanizeRiskKey(t: TFunction, key: string): string {
    const known = RISK_LABEL_KEYS[key];
    if (known) return t(known as Parameters<TFunction>[0]);
    const words = key.replaceAll('_', ' ').trim();
    return words.charAt(0).toUpperCase() + words.slice(1);
}

function isRecord(value: unknown): value is DataRecord {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
}

/** Mapa divisa -> importe ("EUR: 0") como texto "0 € · 12,50 US$". */
function currencyRecord(t: TFunction, f: Formatters, value: unknown): string {
    if (!isRecord(value)) return t('common.na');
    const entries = Object.entries(value);
    if (!entries.length) return t('risk.values.noBalances');
    return entries
        .map(([currency, amount]) => f.formatMoney(amount as number | string, currency))
        .join(' · ');
}

/** Mapa etiqueta -> peso (ratio) como "Tecnología 45,0 % · Salud 20,0 %". */
function exposureRecord(t: TFunction, f: Formatters, value: unknown, labelName: (name: string) => string = (name) => name): string {
    if (!isRecord(value)) return t('common.na');
    const entries = Object.entries(value);
    if (!entries.length) return t('risk.values.noData');
    return entries
        .map(([name, weight]) =>
            `${labelName(name)} ${typeof weight === 'number' ? f.formatPercent(weight, { fromRatio: true, digits: 1 }) : t('common.na')}`,
        )
        .join(' · ');
}

/** F41: el resumen llega con claves internas y JSON crudo; se presenta con
 *  etiquetas en español y valores formateados. Nunca se inventa: null -> NA,
 *  vacios -> estado honesto, claves desconocidas -> humanizadas tal cual. */
function humanizeRiskDashboard(t: TFunction, f: Formatters, dashboard: DataRecord | null): DataRecord | null {
    if (!dashboard) return null;
    const baseCurrency = typeof dashboard.base_currency === 'string' && dashboard.base_currency
        ? dashboard.base_currency
        : 'EUR';
    const display: DataRecord = {};
    for (const [key, value] of Object.entries(dashboard)) {
        const label = humanizeRiskKey(t, key);
        if (key === 'total_value' || key === 'equity_value') {
            display[label] = value === null || value === undefined
                ? `${t('common.na')} ${t('risk.values.missingFxNote')}`
                : f.formatMoney(value as number | string, baseCurrency);
        } else if (key === 'top_1_weight' || key === 'top_5_weight') {
            display[label] = typeof value === 'number' ? f.formatPercent(value, { fromRatio: true, digits: 1 }) : t('common.na');
        } else if (key === 'weight_basis') {
            display[label] = value === 'gross_equity'
                ? t('risk.values.weightBasisGross')
                : t('risk.values.weightBasisTotal');
        } else if (key === 'cash_assets_base' || key === 'margin_debt_base') {
            display[label] = typeof value === 'number' ? f.formatMoney(value, baseCurrency) : t('common.na');
        } else if (key === 'cash' || key === 'cash_native') {
            display[label] = currencyRecord(t, f, value);
        } else if (key === 'sector_exposure') {
            // F208: las claves de sector llegan en inglés del backend y la
            // cabecera las pintaba tal cual; las posiciones ya usan etiquetaSector.
            display[label] = exposureRecord(t, f, value, etiquetaSector);
        } else if (key === 'factor_exposure') {
            display[label] = exposureRecord(t, f, value, etiquetaFactor);
        } else if (key === 'status') {
            display[label] = riskStatusLabels(t)[String(value)] ?? String(value);
        } else if (key === 'missing_fx') {
            // Sin faltas no se pinta la fila: "Sin tipo de cambio para: Ninguno" confundia.
            if (!Array.isArray(value) || value.length === 0) continue;
            display[label] = value
                .map((item) => (isRecord(item) ? String(item.ticker ?? item.quote_currency ?? item.currency ?? '?') : String(item)))
                .join(', ');
        } else if (key === 'valuation_hold') {
            // Como missing_fx: sin posiciones en suspenso no se pinta la fila.
            // Cada entrada declara ticker, motivo y fecha efectiva (risk_service).
            if (!Array.isArray(value) || value.length === 0) continue;
            display[label] = value
                .map((item) => {
                    if (!isRecord(item)) return String(item);
                    const reason = typeof item.reason === 'string' && item.reason ? `: ${item.reason}` : '';
                    const since = typeof item.effective_date === 'string' && item.effective_date ? ` · ${f.formatDate(item.effective_date)}` : '';
                    return `${String(item.ticker ?? '?')}${reason}${since}`;
                })
                .join(' · ');
        } else if (key === 'cash_as_of') {
            display[label] = typeof value === 'string' && value ? f.formatDate(value) : t('common.na');
        } else if (key === 'fx_rates') {
            if (!Array.isArray(value) || value.length === 0) continue;
            display[label] = value
                .map((item) => {
                    if (!isRecord(item) || typeof item.rate !== 'number') return t('common.na');
                    const scope = item.scope === 'cash' ? t('risk.values.fxScopeCash') : t('risk.values.fxScopePositions');
                    return t('risk.values.fxRateLine', {
                        scope,
                        currency: String(item.currency),
                        rate: f.formatNumber(item.rate, { minimumFractionDigits: 4, maximumFractionDigits: 4 }),
                        base: baseCurrency,
                        date: typeof item.as_of === 'string' ? f.formatDate(item.as_of) : t('common.na'),
                    });
                })
                .join(' · ');
        } else if (key === 'valuation_dates_differ') {
            if (value !== true) continue;
            display[label] = t('risk.values.valuationDatesDiffer');
        } else if (key === 'data_as_of') {
            display[label] = typeof value === 'string' && value ? f.formatUserDateTime(value) : t('common.na');
        } else if (key === 'provenance') {
            if (isRecord(value)) {
                const rawSource = typeof value.source === 'string' ? value.source : null;
                const source = rawSource === null ? t('risk.values.sourceInternal') : rawSource === 'CavaAI Postgres' ? t('risk.values.sourceCava') : sourceDisplay(rawSource);
                const fetched = typeof value.fetched_at === 'string' && value.fetched_at
                    ? t('risk.values.fetchedSuffix', { date: f.formatUserDateTime(value.fetched_at) })
                    : '';
                display[label] = `${source}${fetched}`;
            } else {
                display[label] = t('common.na');
            }
        } else if (typeof value === 'boolean') {
            display[label] = value ? t('risk.values.yes') : t('risk.values.no');
        } else {
            display[label] = value;
        }
    }
    return display;
}

/** F43: el valor de mercado llega en divisa base (risk_service.py: value_base)
 *  y se mostraba como numero crudo; el sector llega en ingles y se pintaba tal
 *  cual. Formato monetario con la divisa base y sector con etiqueta ES. */
function positionValueText(t: TFunction, f: Formatters, position: DataRecord, baseCurrency: string): string {
    const value = position.market_value;
    if (value === null || value === undefined || value === '') return t('common.na');
    const numeric = typeof value === 'number' ? value : Number(value);
    if (!Number.isFinite(numeric)) return t('common.na');
    return f.formatMoney(numeric, baseCurrency);
}

function positionSectorText(t: TFunction, position: DataRecord): string {
    const sector = position.sector;
    if (sector === null || sector === undefined || sector === '') return t('common.na');
    return etiquetaSector(String(sector));
}

function weightText(t: TFunction, f: Formatters, position: DataRecord): string {
    const weight = position.weight;
    if (typeof weight === 'number' && Number.isFinite(weight)) {
        return f.formatPercent(weight, { fromRatio: true, digits: 2 });
    }
    return t('common.na');
}

/** Ticker de la posición, enlazado a su ficha de research si se puede resolver. */
function positionLink(position: DataRecord) {
    const ticker = position.ticker;
    const label = formatRecordValue(ticker);
    if (typeof ticker === 'string' && ticker.trim()) {
        const href = `/research/${encodeURIComponent(ticker.trim().toUpperCase())}`;
        return (
            <Link
                href={href}
                className="font-mono font-bold text-teal-300 hover:text-teal-200 hover:underline"
            >
                {label}
            </Link>
        );
    }
    return <span className="font-mono text-gray-300">{label}</span>;
}

/** Identidad de la fila: el ticker es la clave real del holding (viene del
 *  join Position->Company de risk_service.py). El backend entrega las
 *  posiciones ordenadas por peso, así que el orden cambia en cada refresco:
 *  con `key={index}` React reutilizaba el nodo de otra fila. */
function positionKey(position: DataRecord): string {
    const ticker = typeof position.ticker === 'string' ? position.ticker.trim().toUpperCase() : '';
    if (ticker) return ticker;
    const name = typeof position.name === 'string' ? position.name.trim() : '';
    return name || `sin-ticker:${String(position.as_of ?? '')}`;
}

/** Identidad de la alerta: la regla (umbral) más el sujeto al que se aplica
 *  (ticker, o el mensaje cuando la alerta es de caja y no hay ticker). */
function alertKey(alert: DataRecord): string {
    const ticker = typeof alert.ticker === 'string' ? alert.ticker.trim().toUpperCase() : '';
    const subject = ticker || formatRecordValue(alert.message);
    return `${subject}#${String(alert.threshold ?? '')}`;
}

export default function RiskDashboardView({ initialDashboard }: RiskDashboardViewProps) {
    const t = useT();
    const f = useFormat();
    const [dashboard, setDashboard] = useState(initialDashboard);
    // Sincroniza el snapshot si el servidor revalida: ajuste durante el
    // render, no efecto con setState síncrono.
    const [prevInitial, setPrevInitial] = useState(initialDashboard);
    if (prevInitial !== initialDashboard) {
        setPrevInitial(initialDashboard);
        setDashboard(initialDashboard);
    }

    const refreshDashboard = async () => {
        // Una única respuesta actualiza resumen, alertas, posiciones y divisa.
        // Si falla, no sustituimos el snapshot anterior por datos vacíos.
        const next = await getRiskDashboard();
        setDashboard(next);
        return humanizeRiskDashboard(t, f, headlineRecord(next));
    };
    const positions = extractPositions(dashboard);
    const alerts = extractAlerts(dashboard);
    // Cartera nueva (valor 0 y sin posiciones): siguiente paso claro en vez de un «sin datos».
    const isEmptyPortfolio = !!dashboard && Number(dashboard.total_value ?? NaN) === 0 && Number(dashboard.equity_value ?? 0) === 0;
    const highAlerts = alerts.filter(alert => alert.severity === 'high').length;
    const weightLabel = dashboard?.weight_basis === 'gross_equity'
        ? t('risk.positions.weightGross')
        : ['total_with_cash', 'with_cash'].includes(String(dashboard?.weight_basis))
            ? t('risk.positions.weightWithCash')
            : t('risk.positions.weightUnknown');
    // F43: misma regla que en el resumen - la divisa base viene del dashboard.
    const baseCurrency = dashboard && typeof dashboard.base_currency === 'string' && dashboard.base_currency
        ? dashboard.base_currency
        : 'EUR';

    return (
        <div className="grid gap-6">


            <Card className="rounded-lg border border-gray-700 bg-gray-800/50">
                <CardHeader className="border-b border-gray-700/50 pb-4">
                    <div className="flex items-center gap-3">
                        <Gauge className="h-5 w-5 text-teal-400" aria-hidden="true" />
                        <div>
                            <CardTitle as="h2" className="text-lg font-semibold text-gray-100">
                                {t('risk.alerts.title')}
                            </CardTitle>
                            {highAlerts > 0 ? <p className="mt-1 text-sm text-amber-300">{f.formatCount(highAlerts, t('risk.alerts.highOne'), t('risk.alerts.highMany'))}</p> : null}
                        </div>
                    </div>
                </CardHeader>
                <CardContent className="pt-4">
                    {alerts.length === 0 ? (
                        <p className="py-6 text-center text-sm text-gray-500">
                            {dashboard?.status === 'ok'
                                ? t('risk.alerts.emptyOk')
                                : t('risk.alerts.emptyIncomplete')}
                        </p>
                    ) : (
                        <div className="space-y-3">
                            {alerts.map((alert) => (
                                <div className="rounded-md border border-gray-700/60 bg-black/20 p-3" key={alertKey(alert)}>
                                    <div className="flex flex-wrap items-center gap-2">
                                        <Badge variant="outline">{etiquetaSeveridad(formatRecordValue(alert.severity))}</Badge>
                                        <span className="text-sm text-gray-200">{formatRecordValue(alert.message)}</span>
                                    </div>
                                    <p className="mt-2 text-xs leading-5 text-gray-400">{thresholdExplanation(t, alert)}</p>
                                </div>
                            ))}
                        </div>
                    )}
                </CardContent>
            </Card>

            <RecordDetail
                title={t('risk.summary.title')}
                titleAs="h2"
                icon={<Gauge className="h-5 w-5 text-teal-400" aria-hidden="true" />}
                record={humanizeRiskDashboard(t, f, headlineRecord(dashboard))}
                fetchRecord={refreshDashboard}
                maxKeys={32}
                hiddenKeys={['trace']}
                emptyMessage={t('risk.summary.empty')}
            />

            <Card className="rounded-lg border border-gray-700 bg-gray-800/50">
                <CardHeader className="flex flex-row items-center justify-between space-y-0 border-b border-gray-700/50 pb-4">
                    <div className="flex items-center gap-3">
                        <Briefcase className="h-5 w-5 text-teal-400" aria-hidden="true" />
                        <div>
                            <CardTitle as="h2" className="text-lg font-semibold text-gray-100">
                                {t('risk.positions.title')}
                            </CardTitle>
                        </div>
                    </div>
                    <Link
                        href="/portfolio"
                        className="text-sm font-semibold text-teal-300 hover:text-teal-200"
                    >
                        {t('risk.positions.viewPortfolio')}
                    </Link>
                </CardHeader>
                <CardContent className="pt-4">
                    {positions.length === 0 && isEmptyPortfolio ? (
                        <div className="py-8 text-center text-sm text-gray-400">
                            <p>{t('risk.positions.emptyPortfolio')}</p>
                            <Link
                                href="/portfolio?anadir=1"
                                className="mt-3 inline-flex min-h-11 items-center rounded-lg bg-teal-400/10 px-3 font-medium text-teal-300 hover:bg-teal-400/20"
                            >
                                {t('risk.positions.addInvestment')}
                            </Link>
                        </div>
                    ) : positions.length === 0 ? (
                        <p className="py-10 text-center text-sm text-gray-500">
                            {t('risk.positions.empty')}
                        </p>
                    ) : (
                        <>
                            {/* Escritorio: tabla completa, con la región de scroll enfocada por teclado */}
                            <div className="hidden overflow-x-auto md:block">
                                <Table regionLabel={t('risk.positions.tableRegion')}>
                                    <TableCaption className="sr-only">{t('risk.positions.tableCaption')}</TableCaption>
                                    <TableHeader>
                                        <TableRow className="border-gray-700 hover:bg-transparent">
                                            <TableHead className="text-xs font-semibold uppercase text-gray-500">{t('risk.positions.colTicker')}</TableHead>
                                            <TableHead className="text-xs font-semibold uppercase text-gray-500">{t('risk.positions.colName')}</TableHead>
                                            <TableHead className="text-xs font-semibold uppercase text-gray-500">{t('risk.positions.colSector')}</TableHead>
                                            <TableHead className="text-right text-xs font-semibold uppercase text-gray-500">{t('risk.positions.colValue')}</TableHead>
                                            <TableHead className="text-right text-xs font-semibold uppercase text-gray-500">{weightLabel}</TableHead>
                                        </TableRow>
                                    </TableHeader>
                                    <TableBody>
                                        {positions.map((position) => (
                                            <TableRow key={positionKey(position)} className="border-gray-700/50">
                                                <TableCell>{positionLink(position)}</TableCell>
                                                <TableCell className="text-sm text-gray-300">
                                                    {formatRecordValue(position.name)}
                                                </TableCell>
                                                <TableCell className="text-sm text-gray-400">
                                                    {positionSectorText(t, position)}
                                                </TableCell>
                                                <TableCell className="text-right text-sm text-gray-200">
                                                    {positionValueText(t, f, position, baseCurrency)}
                                                </TableCell>
                                                <TableCell className="text-right text-sm font-semibold text-gray-100">
                                                    {weightText(t, f, position)}
                                                </TableCell>
                                            </TableRow>
                                        ))}
                                    </TableBody>
                                </Table>
                            </div>
                            {/* Móvil: cards equivalentes, sin scroll horizontal */}
                            <ul className="space-y-3 md:hidden">
                                {positions.map((position) => (
                                    <li className="min-w-0 rounded-xl border border-gray-700/50 bg-gray-800/40 p-4" key={positionKey(position)}>
                                        {positionLink(position)}
                                        <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2">
                                            <div className="min-w-0">
                                                <dt className="text-[11px] uppercase tracking-wide text-gray-500">{t('risk.positions.colName')}</dt>
                                                <dd className="break-words text-sm text-gray-300">{formatRecordValue(position.name)}</dd>
                                            </div>
                                            <div className="min-w-0">
                                                <dt className="text-[11px] uppercase tracking-wide text-gray-500">{t('risk.positions.colSector')}</dt>
                                                <dd className="break-words text-sm text-gray-400">{positionSectorText(t, position)}</dd>
                                            </div>
                                            <div className="min-w-0">
                                                <dt className="text-[11px] uppercase tracking-wide text-gray-500">{t('risk.positions.colValue')}</dt>
                                                <dd className="break-words text-right text-sm text-gray-200">{positionValueText(t, f, position, baseCurrency)}</dd>
                                            </div>
                                            <div className="min-w-0">
                                                <dt className="text-[11px] uppercase tracking-wide text-gray-500">{weightLabel}</dt>
                                                <dd className="break-words text-right text-sm font-semibold text-gray-100">{weightText(t, f, position)}</dd>
                                            </div>
                                        </dl>
                                    </li>
                                ))}
                            </ul>
                        </>
                    )}
                </CardContent>
            </Card>
        </div>
    );
}
