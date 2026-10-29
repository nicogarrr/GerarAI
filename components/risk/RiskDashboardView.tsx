'use client';

import Link from 'next/link';
import { useState } from 'react';
import { Briefcase, Gauge } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { RecordDetail, formatRecordValue, type DataRecord } from '@/components/data/RecordViews';
import { etiquetaFactor, etiquetaSector, etiquetaSeveridad } from '@/lib/labels';
import { formatDate, formatUserDateTime, formatMoney, formatNumber, formatPercent, NA } from '@/lib/format';
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
function thresholdExplanation(alert: DataRecord): string {
    const threshold = alert.threshold;
    if (threshold === 0.2) {
        return 'Umbral 20% del valor de la cartera: por encima, una sola posición concentra el riesgo. Regla de concentración, no un VaR ni una probabilidad de pérdida.';
    }
    if (threshold === 0.1) {
        return 'Umbral 10% para empresas pre-FCF (todavía no generan caja libre): el doble de estricto que el 20% general.';
    }
    if (threshold === 0) {
        return 'La caja de esta divisa está en negativo (saldo deudor). Revisa los saldos o las operaciones en esa divisa; el umbral es no bajar de cero.';
    }
    return 'Alerta disparada al superar el umbral indicado junto al valor medido.';
}

/** Resumen sin arrays anidados (positions/alerts se muestran en su propia tabla) */
function headlineRecord(dashboard: DataRecord | null): DataRecord | null {
    if (!dashboard) return null;
    const { positions: _positions, alerts: _alerts, ...rest } = dashboard;
    void _positions;
    void _alerts;
    return rest;
}

const RISK_LABELS: Record<string, string> = {
    total_value: 'Valor total',
    equity_value: 'Valor en renta variable',
    cash: 'Caja',
    top_1_weight: 'Peso de la mayor posición',
    top_5_weight: 'Peso de las 5 mayores',
    weight_basis: 'Base de los pesos',
    cash_assets_base: 'Caja a favor',
    margin_debt_base: 'Deuda de margen',
    sector_exposure: 'Exposición por sector',
    factor_exposure: 'Exposición por factor',
    status: 'Datos del cálculo',
    base_currency: 'Divisa base',
    cash_native: 'Caja en divisa original',
    missing_fx: 'Sin tipo de cambio para',
    data_as_of: 'Datos a fecha de',
    provenance: 'Fuente',
    cash_as_of: 'Caja a fecha de',
    fx_rates: 'Tipos de cambio usados',
    valuation_dates_differ: 'Fechas de valoración',
    valuation_hold: 'Valoración en suspenso',
};

const RISK_STATUS_LABELS: Record<string, string> = {
    ok: 'Completos',
    incomplete_fx: 'Incompleto: faltan tipos de cambio',
    insufficient_data: 'Datos insuficientes',
    incomplete_valuation: 'Incompleto: valoración en suspenso',
};

function humanizeRiskKey(key: string): string {
    const known = RISK_LABELS[key];
    if (known) return known;
    const words = key.replaceAll('_', ' ').trim();
    return words.charAt(0).toUpperCase() + words.slice(1);
}

function isRecord(value: unknown): value is DataRecord {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
}

/** Mapa divisa -> importe ("EUR: 0") como texto "0 € · 12,50 US$". */
function currencyRecord(value: unknown): string {
    if (!isRecord(value)) return NA;
    const entries = Object.entries(value);
    if (!entries.length) return 'Sin saldos';
    return entries
        .map(([currency, amount]) => formatMoney(amount as number | string, currency))
        .join(' · ');
}

/** Mapa etiqueta -> peso (ratio) como "Tecnología 45,0 % · Salud 20,0 %". */
function exposureRecord(value: unknown, labelName: (name: string) => string = (name) => name): string {
    if (!isRecord(value)) return NA;
    const entries = Object.entries(value);
    if (!entries.length) return 'Sin datos';
    return entries
        .map(([name, weight]) =>
            `${labelName(name)} ${typeof weight === 'number' ? formatPercent(weight, { fromRatio: true, digits: 1 }) : NA}`,
        )
        .join(' · ');
}

/** F41: el resumen llega con claves internas y JSON crudo; se presenta con
 *  etiquetas en español y valores formateados. Nunca se inventa: null -> NA,
 *  vacios -> estado honesto, claves desconocidas -> humanizadas tal cual. */
function humanizeRiskDashboard(dashboard: DataRecord | null): DataRecord | null {
    if (!dashboard) return null;
    const baseCurrency = typeof dashboard.base_currency === 'string' && dashboard.base_currency
        ? dashboard.base_currency
        : 'EUR';
    const display: DataRecord = {};
    for (const [key, value] of Object.entries(dashboard)) {
        const label = humanizeRiskKey(key);
        if (key === 'total_value' || key === 'equity_value') {
            display[label] = value === null || value === undefined
                ? `${NA} (faltan tipos de cambio)`
                : formatMoney(value as number | string, baseCurrency);
        } else if (key === 'top_1_weight' || key === 'top_5_weight') {
            display[label] = typeof value === 'number' ? formatPercent(value, { fromRatio: true, digits: 1 }) : NA;
        } else if (key === 'weight_basis') {
            display[label] = value === 'gross_equity'
                ? 'Valor bruto de las posiciones (la caja es negativa)'
                : 'Total con caja';
        } else if (key === 'cash_assets_base' || key === 'margin_debt_base') {
            display[label] = typeof value === 'number' ? formatMoney(value, baseCurrency) : NA;
        } else if (key === 'cash' || key === 'cash_native') {
            display[label] = currencyRecord(value);
        } else if (key === 'sector_exposure') {
            // F208: las claves de sector llegan en inglés del backend y la
            // cabecera las pintaba tal cual; las posiciones ya usan etiquetaSector.
            display[label] = exposureRecord(value, etiquetaSector);
        } else if (key === 'factor_exposure') {
            display[label] = exposureRecord(value, etiquetaFactor);
        } else if (key === 'status') {
            display[label] = RISK_STATUS_LABELS[String(value)] ?? String(value);
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
                    const since = typeof item.effective_date === 'string' && item.effective_date ? ` · ${formatDate(item.effective_date)}` : '';
                    return `${String(item.ticker ?? '?')}${reason}${since}`;
                })
                .join(' · ');
        } else if (key === 'cash_as_of') {
            display[label] = typeof value === 'string' && value ? formatDate(value) : NA;
        } else if (key === 'fx_rates') {
            if (!Array.isArray(value) || value.length === 0) continue;
            display[label] = value
                .map((item) => {
                    if (!isRecord(item) || typeof item.rate !== 'number') return NA;
                    const scope = item.scope === 'cash' ? 'Caja' : 'Posiciones';
                    return `${scope}: 1 ${String(item.currency)} = ${formatNumber(item.rate, { minimumFractionDigits: 4, maximumFractionDigits: 4 })} ${baseCurrency} (${typeof item.as_of === 'string' ? formatDate(item.as_of) : NA})`;
                })
                .join(' · ');
        } else if (key === 'valuation_dates_differ') {
            if (value !== true) continue;
            display[label] = 'Posiciones y caja a fechas distintas: el total combina ambas';
        } else if (key === 'data_as_of') {
            display[label] = typeof value === 'string' && value ? formatUserDateTime(value) : NA;
        } else if (key === 'provenance') {
            if (isRecord(value)) {
                const rawSource = typeof value.source === 'string' ? value.source : null;
                const source = rawSource === null ? 'Fuente interna' : rawSource === 'CavaAI Postgres' ? 'Base de datos de GerarAI' : sourceDisplay(rawSource);
                const fetched = typeof value.fetched_at === 'string' && value.fetched_at
                    ? ` · ${formatUserDateTime(value.fetched_at)}`
                    : '';
                display[label] = `${source}${fetched}`;
            } else {
                display[label] = NA;
            }
        } else if (typeof value === 'boolean') {
            display[label] = value ? 'Sí' : 'No';
        } else {
            display[label] = value;
        }
    }
    return display;
}

/** F43: el valor de mercado llega en divisa base (risk_service.py: value_base)
 *  y se mostraba como numero crudo; el sector llega en ingles y se pintaba tal
 *  cual. Formato monetario con la divisa base y sector con etiqueta ES. */
function positionValueText(position: DataRecord, baseCurrency: string): string {
    const value = position.market_value;
    if (value === null || value === undefined || value === '') return NA;
    const numeric = typeof value === 'number' ? value : Number(value);
    if (!Number.isFinite(numeric)) return NA;
    return formatMoney(numeric, baseCurrency);
}

function positionSectorText(position: DataRecord): string {
    const sector = position.sector;
    if (sector === null || sector === undefined || sector === '') return NA;
    return etiquetaSector(String(sector));
}

function weightText(position: DataRecord): string {
    const weight = position.weight;
    if (typeof weight === 'number' && Number.isFinite(weight)) {
        return formatPercent(weight, { fromRatio: true, digits: 2 });
    }
    return NA;
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
        return humanizeRiskDashboard(headlineRecord(next));
    };
    const positions = extractPositions(dashboard);
    const alerts = extractAlerts(dashboard);
    const highAlerts = alerts.filter(alert => alert.severity === 'high').length;
    const weightLabel = dashboard?.weight_basis === 'gross_equity'
        ? 'Peso (valor bruto)'
        : ['total_with_cash', 'with_cash'].includes(String(dashboard?.weight_basis))
            ? 'Peso (con caja)'
            : 'Peso (base no disponible)';
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
                                Alertas de concentración y liquidez
                            </CardTitle>
                            {highAlerts > 0 ? <p className="mt-1 text-sm text-amber-300">{highAlerts} {highAlerts === 1 ? 'alerta alta' : 'alertas altas'}</p> : null}
                        </div>
                    </div>
                </CardHeader>
                <CardContent className="pt-4">
                    {alerts.length === 0 ? (
                        <p className="py-6 text-center text-sm text-gray-500">
                            {dashboard?.status === 'ok'
                                ? 'Sin alertas de concentración o liquidez en los datos calculados.'
                                : 'No hay alertas en los datos disponibles. La cobertura incompleta no permite descartar alertas en el resto de la cartera.'}
                        </p>
                    ) : (
                        <div className="space-y-3">
                            {alerts.map((alert) => (
                                <div className="rounded-md border border-gray-700/60 bg-black/20 p-3" key={alertKey(alert)}>
                                    <div className="flex flex-wrap items-center gap-2">
                                        <Badge variant="outline">{etiquetaSeveridad(formatRecordValue(alert.severity))}</Badge>
                                        <span className="text-sm text-gray-200">{formatRecordValue(alert.message)}</span>
                                    </div>
                                    <p className="mt-2 text-xs leading-5 text-gray-400">{thresholdExplanation(alert)}</p>
                                </div>
                            ))}
                        </div>
                    )}
                </CardContent>
            </Card>

            <RecordDetail
                title="Exposiciones de cartera"
                titleAs="h2"
                icon={<Gauge className="h-5 w-5 text-teal-400" aria-hidden="true" />}
                record={humanizeRiskDashboard(headlineRecord(dashboard))}
                fetchRecord={refreshDashboard}
                maxKeys={32}
                hiddenKeys={['trace']}
                emptyMessage="No hay métricas de riesgo disponibles. Comprueba que tu cartera tiene posiciones."
            />

            <Card className="rounded-lg border border-gray-700 bg-gray-800/50">
                <CardHeader className="flex flex-row items-center justify-between space-y-0 border-b border-gray-700/50 pb-4">
                    <div className="flex items-center gap-3">
                        <Briefcase className="h-5 w-5 text-teal-400" aria-hidden="true" />
                        <div>
                            <CardTitle as="h2" className="text-lg font-semibold text-gray-100">
                                Exposición por posición
                            </CardTitle>
                        </div>
                    </div>
                    <Link
                        href="/portfolio"
                        className="text-sm font-semibold text-teal-300 hover:text-teal-200"
                    >
                        Ver cartera →
                    </Link>
                </CardHeader>
                <CardContent className="pt-4">
                    {positions.length === 0 ? (
                        <p className="py-10 text-center text-sm text-gray-500">
                            Sin posiciones con exposición calculada.
                        </p>
                    ) : (
                        <>
                            {/* Escritorio: tabla completa, con la región de scroll enfocada por teclado */}
                            <div className="hidden overflow-x-auto md:block">
                                <Table regionLabel="Exposición por posición">
                                    <TableCaption className="sr-only">Exposición por posición: valor de mercado y peso de cada holding</TableCaption>
                                    <TableHeader>
                                        <TableRow className="border-gray-700 hover:bg-transparent">
                                            <TableHead className="text-xs font-semibold uppercase text-gray-500">Ticker</TableHead>
                                            <TableHead className="text-xs font-semibold uppercase text-gray-500">Nombre</TableHead>
                                            <TableHead className="text-xs font-semibold uppercase text-gray-500">Sector</TableHead>
                                            <TableHead className="text-right text-xs font-semibold uppercase text-gray-500">Valor</TableHead>
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
                                                    {positionSectorText(position)}
                                                </TableCell>
                                                <TableCell className="text-right text-sm text-gray-200">
                                                    {positionValueText(position, baseCurrency)}
                                                </TableCell>
                                                <TableCell className="text-right text-sm font-semibold text-gray-100">
                                                    {weightText(position)}
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
                                                <dt className="text-[11px] uppercase tracking-wide text-gray-500">Nombre</dt>
                                                <dd className="break-words text-sm text-gray-300">{formatRecordValue(position.name)}</dd>
                                            </div>
                                            <div className="min-w-0">
                                                <dt className="text-[11px] uppercase tracking-wide text-gray-500">Sector</dt>
                                                <dd className="break-words text-sm text-gray-400">{positionSectorText(position)}</dd>
                                            </div>
                                            <div className="min-w-0">
                                                <dt className="text-[11px] uppercase tracking-wide text-gray-500">Valor</dt>
                                                <dd className="break-words text-right text-sm text-gray-200">{positionValueText(position, baseCurrency)}</dd>
                                            </div>
                                            <div className="min-w-0">
                                                <dt className="text-[11px] uppercase tracking-wide text-gray-500">{weightLabel}</dt>
                                                <dd className="break-words text-right text-sm font-semibold text-gray-100">{weightText(position)}</dd>
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
