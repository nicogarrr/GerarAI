'use client';

import { useState, useSyncExternalStore } from 'react';
import { useRouter } from 'next/navigation';
import { Download, FileText, Receipt, RotateCcw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
    RecordDetail,
    RecordList,
    researchHrefFor,
    type DataRecord,
} from '@/components/data/RecordViews';
import { getTaxHoldings, getTaxReport, regenerateTaxReport } from '@/lib/actions/taxes.actions';
import { FilingSection, Modelo720Section } from '@/components/taxes/FilingSections';
import { recordDetailKey } from '@/components/taxes/record-detail-key';
import { reportForYear, type ReportOverride } from '@/lib/taxes/report-state';
import { formatUserDateTime, formatMoney, formatNumber, isValidCurrencyCode, NA, USER_TZ, formatCountEs } from '@/lib/format';
import { t } from '@/lib/i18n/t';
import { showErrorToast } from '@/lib/toast';
import { toast } from 'sonner';
import { onTheFlyReportNote } from '@/lib/taxes/report-note';
import { TAX_HOLDING_MONEY_COLUMNS, formatHoldingCell } from '@/lib/taxes/holding-money';

interface TaxesViewProps {
    initialHoldings: DataRecord[];
    initialReport: DataRecord | null;
    initialThresholds720: DataRecord | null;
    initialFile720: DataRecord | null;
    initialThresholds720Unavailable?: boolean;
    year: number;
}

/** El endpoint envuelve las métricas en {summary, dividends, realized, misc}:
 *  para mostrarlas se aplana `summary` (métricas fiscales legibles) y se
 *  conserva generated_at; las listas crudas no se pintan como JSON. */
function toDisplayReport(raw: DataRecord | null): DataRecord | null {
    if (!raw || typeof raw !== 'object') return null;
    const summary = raw.summary;
    if (summary === null || typeof summary !== 'object' || Array.isArray(summary)) return raw;
    const display: DataRecord = { ...(summary as DataRecord) };
    if (raw.generated_at) display.generated_at = raw.generated_at;
    const humanized = humanizeTaxReport(display);
    // F183: sin `generated_at` y con `persisted=false` el informe se
    // calculó al vuelo y no está guardado: la fila «Generado» lo declara
    // en lugar de simplemente no existir.
    const onTheFly = onTheFlyReportNote(raw);
    if (onTheFly) humanized[TAX_LABELS.generated_at] = onTheFly;
    return humanized;
}

/** Aviso de informe guardado con un criterio de cálculo anterior. Sale del
 *  bloque `versioning` que calcula el backend (tax_report_versioning.py): la UI
 *  no decide nada, solo lo muestra. Sin `versioning` (backend antiguo) o con
 *  `stale` distinto de true no hay aviso. */
function staleReportNotice(raw: DataRecord | null): string | null {
    const versioning = raw?.versioning;
    if (!versioning || typeof versioning !== 'object' || Array.isArray(versioning)) return null;
    if ((versioning as DataRecord).stale !== true) return null;
    const outdated = (versioning as DataRecord).outdated;
    const markers = Array.isArray(outdated) ? outdated : [];
    const missing = markers.some((item) => (item as DataRecord | null)?.reason === 'criterio_no_registrado');
    const why = missing
        ? 'se guardó antes de registrar el criterio de cálculo'
        : 'se guardó con un criterio de cálculo anterior al vigente';
    return `Este informe ${why}: las cifras guardadas pueden no reflejar las reglas actuales. Regenéralo para recalcularlo; hasta entonces no lo tomes como actualizado.`;
}

/** Etiquetas en español para las claves conocidas del resumen fiscal (F20).
 *  Las claves desconocidas se humanizan (snake_case -> frase) sin ocultarse. */
const TAX_LABELS: Record<string, string> = {
    fiscal_year: 'Ejercicio',
    base_currency: 'Divisa base',
    total_dividends_base: 'Dividendos brutos',
    total_withholding_base: 'Retenciones soportadas',
    total_realized_gain_base: 'Plusvalías/minusvalías realizadas',
    total_blocked_loss_base: 'Minusvalías bloqueadas (regla de los 2 meses)',
    net_taxable_base: 'Base neta estimada',
    wash_sale_rule: 'Regla anti-recompra',
    wash_sale_basis: 'Criterio anti-recompra',
    fiscal_disclaimer: 'Aviso fiscal',
    wash_sale_window_open: 'Ventana anti-recompra abierta en',
    dividend_count: 'Dividendos (nº)',
    sell_count: 'Ventas (nº)',
    over_sell: 'Ventas sin compras que las cubran',
    cost_unknown: 'Ventas con coste heredado desconocido',
    method: 'Método de valoración',
    securities_fx_criterion: 'Criterio FX en valores',
    currency_ledger_criterion: 'Criterio libro de divisas',
    currency_ledger_status: 'Libro de divisas (USD a EUR)',
    currency_ledger_gain_base: 'G/P por conversión de divisa',
    currency_ledger_reason: 'Libro de divisas: motivo',
    currency_ledger_blocked_loss_base: 'Pérdida de divisa diferida (recompra en el año posterior)',
    currency_ledger_note: 'Libro de divisas: nota de criterio',
    currency_ledger_by_currency: 'Libro de divisas por divisa',
    incomplete_fx: 'Tipos de cambio incompletos',
    missing_fx: 'Sin tipo de cambio para',
    generated_at: 'Generado',
    unattributed_tickers: 'Tickers sin atribuir',
    unattributed_dividends_base: 'Dividendos sin atribuir',
    inconsistent_cash_rows: 'Filas de caja inconsistentes',
    ambiguous_cash: 'Tickers con caja ambigua',
    manual_review: 'Revisión manual',
};

/** Valores conocidos del método de valoración (el backend manda el id en
 *  minúsculas, p.ej. `fifo`, que en UI se veía en crudo). */
const METHOD_LABELS: Record<string, string> = {
    fifo: 'FIFO',
};

const SECURITIES_FX_LABELS: Record<string, string> = {
    // Criterio DGT: ganancia en la divisa del valor, convertida una sola vez
    // al cambio de la fecha de venta (tax_report_service.py).
    dgt_native_gain_sale_date_v1: 'Ganancia en divisa del valor, convertida a EUR al cambio de la fecha de venta (DGT)',
};

const WASH_RULE_LABELS: Record<string, string> = {
    'es-irpf-2m': 'IRPF español: no recomprar en 2 meses',
};

const WASH_BASIS_LABELS: Record<string, string> = {
    'manual-aeat-2025': 'Manual AEAT 2025 (proporcional + FIFO)',
};

function humanizeKey(key: string): string {
    const known = TAX_LABELS[key];
    if (known) return known;
    const words = key.replaceAll('_', ' ').trim();
    return words.charAt(0).toUpperCase() + words.slice(1);
}

/** El backend etiqueta el efectivo sin compañía resuelta como
 *  `UNATTRIBUTED:SIMBOLO` (o `UNATTRIBUTED:DIVISA:ACCION` cuando ni eso se
 *  recuperó). Es un identificador interno estable, no copy de UI: aquí se
 *  traduce a español conservando el símbolo, que es la parte útil. */
function humanizeUnattributedTicker(item: string): string {
    const match = /^UNATTRIBUTED:(.+)$/.exec(item);
    if (!match) return item;
    return `Sin atribuir: ${match[1]}`;
}

/** Filas de caja inconsistentes del resumen: el importe es un CANDIDATO
 *  (price x quantity no canónica), nunca un pago medido; se lista legible
 *  para su revisión manual en vez de volcarse como objeto crudo. */
function formatInconsistentCashRows(value: unknown): string {
    if (!Array.isArray(value) || value.length === 0) return 'Ninguna';
    return (value as DataRecord[]).map((row) => {
        const ticker = typeof row.ticker === 'string' && row.ticker ? row.ticker : NA;
        const date = typeof row.date === 'string' && row.date ? row.date : NA;
        const action = typeof row.action === 'string' && row.action ? row.action : NA;
        // Una divisa ausente o rara NUNCA se sustituye (regla de lib/format):
        // sin divisa válida el importe se omite, no se etiqueta como EUR.
        const code = typeof row.currency === 'string' ? row.currency.trim().toUpperCase() : '';
        const currency = isValidCurrencyCode(code) ? code : null;
        const amount = row.amount === null || row.amount === undefined || currency === null
            ? null
            : `${formatMoney(row.amount as number | string, currency)} (candidato)`;
        return [ticker, date, action, amount].filter((part) => part !== null).join(' · ');
    }).join(' | ');
}

/** Convierte el resumen fiscal a filas etiquetadas en español con valores
 *  formateados (importes con divisa, listas de tickers, fechas). Nunca
 *  inventa: los null quedan como `NA` («N/D») y las claves raras se
 *  humanizan. */
function humanizeTaxReport(summary: DataRecord): DataRecord {
    const currency = typeof summary.base_currency === 'string' && summary.base_currency
        ? summary.base_currency
        : 'EUR';
    const moneyKeys = new Set([
        'total_dividends_base',
        'total_withholding_base',
        'total_realized_gain_base',
        'total_blocked_loss_base',
        'net_taxable_base',
        'unattributed_dividends_base',
    ]);
    const listKeys = new Set(['wash_sale_window_open', 'over_sell', 'cost_unknown', 'missing_fx', 'unattributed_tickers', 'ambiguous_cash']);
    // La causa del null importa: con FX presente pero una fila de caja
    // ambigua sin resolver, decir "faltan tipos de cambio" miente. Se
    // declaran ambas causas si coexisten.
    const missingFx = Array.isArray(summary.missing_fx) && summary.missing_fx.length > 0;
    const ambiguousCash = summary.manual_review === true
        || (Array.isArray(summary.ambiguous_cash) && summary.ambiguous_cash.length > 0);
    const overSold = Array.isArray(summary.over_sell) ? summary.over_sell.map(String) : [];
    const costUnknown = Array.isArray(summary.cost_unknown) ? summary.cost_unknown.map(String) : [];
    const nullReason = [
        overSold.length > 0 ? `ventas sin compras que las cubran: ${overSold.join(', ')}` : null,
        costUnknown.length > 0
            ? `coste heredado de una venta descubierta: ${costUnknown.join(', ')}`
            : null,
        ambiguousCash ? 'revisión manual: fila de caja ambigua' : null,
        missingFx ? 'faltan tipos de cambio' : null,
    ].filter(Boolean).join(' y ');
    const nullLabel = nullReason ? `${NA} (${nullReason})` : NA;
    const display: DataRecord = {};
    for (const [key, value] of Object.entries(summary)) {
        const label = humanizeKey(key);
        if (moneyKeys.has(key)) {
            display[label] = value === null || value === undefined
                ? nullLabel
                : formatMoney(value as number | string, currency);
        } else if (listKeys.has(key)) {
            display[label] = Array.isArray(value) && value.length > 0
                ? value.map((item) => humanizeUnattributedTicker(String(item))).join(', ')
                : 'Ninguno';
        } else if (key === 'inconsistent_cash_rows') {
            display[label] = formatInconsistentCashRows(value);
        } else if (key === 'wash_sale_rule') {
            display[label] = WASH_RULE_LABELS[String(value)] ?? String(value);
        } else if (key === 'wash_sale_basis') {
            display[label] = WASH_BASIS_LABELS[String(value)] ?? String(value);
        } else if (key === 'securities_fx_criterion') {
            display[label] = SECURITIES_FX_LABELS[String(value)] ?? String(value);
        } else if (key === 'currency_ledger_status') {
            display[label] = ({ not_computed: 'No calculado', incomplete: 'Incompleto', computed: 'Calculado' } as Record<string, string>)[String(value)] ?? String(value);
        } else if (key === 'currency_ledger_gain_base') {
            display[label] = value === null || value === undefined ? 'No calculado' : value;
        } else if (key === 'currency_ledger_by_currency') {
            const byCurrency = (value ?? {}) as Record<string, { status?: string; gain_base?: number | null; unconverted?: number | null }>;
            const names: Record<string, string> = { not_computed: 'No calculado', incomplete: 'Incompleto', computed: 'Calculado' };
            const parts = Object.entries(byCurrency).map(([cur, v]) => `${cur}: ${v.gain_base === null || v.gain_base === undefined ? 'No calculado' : `${v.gain_base} EUR`} (${names[String(v.status)] ?? String(v.status)}${v.unconverted === null || v.unconverted === undefined ? '' : `, sin convertir ${v.unconverted} ${cur}`})`);
            display[label] = parts.length > 0 ? parts.join(' · ') : 'Sin conversiones';
        } else if (key === 'currency_ledger_reason') {
            display[label] = value ?? 'Ninguno';
        } else if (key === 'method') {
            display[label] = METHOD_LABELS[String(value).toLowerCase()] ?? String(value);
        } else if (key === 'generated_at') {
            display[label] = formatUserDateTime(value as string);
        } else if (typeof value === 'boolean') {
            display[label] = value ? 'Sí' : 'No';
        } else {
            display[label] = value;
        }
    }
    return display;
}

function csvCell(value: string): string {
    return `"${value.replaceAll('"', '""')}"`;
}

/** Serialización COMPLETA para la exportación. Los formateadores de pantalla
 *  (describeValue/formatRecordValue) truncan entradas («+N más») y caracteres
 *  («…» a los 400) para caber en una celda con clamp: un resumen fiscal
 *  descargable no puede perder datos (perdía 16 de 22 campos del summary y
 *  la sección loss_compensation entera). Mismo formato «clave: valor · …». */
function csvFullValue(value: unknown, depth = 8): string {
    if (value === null || value === undefined) return '—';
    if (typeof value === 'boolean') return value ? 'Sí' : 'No';
    if (typeof value === 'number') return String(value);
    if (typeof value === 'string') return value;
    if (value instanceof Date) return value.toISOString();
    if (depth <= 0) return JSON.stringify(value);
    if (Array.isArray(value)) {
        if (value.length === 0) return '—';
        return value.map((item) => csvFullValue(item, depth - 1)).join(' · ');
    }
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) return '—';
    return entries
        .map(([key, item]) => `${humanizeKey(key)}: ${csvFullValue(item, depth - 1)}`)
        .join(' · ');
}

/** Neutraliza fórmulas de hoja de cálculo (convención `_csv_cell` del
 *  backend, export.py): si el valor ORIGINAL es texto y empieza por
 *  = + - @ | %, la celda lleva prefijo '. Un número negativo (-10) queda
 *  intacto: las hojas ya lo parsean como número; una cadena '-10' sí se
 *  neutraliza, igual que el backend (isinstance str). Las comillas de
 *  csvCell solo protegen la estructura del CSV, no la interpretación
 *  como fórmula. */
function csvExportCell(value: unknown): string {
    const text = csvFullValue(value);
    if (typeof value === 'string' && /^[=+\-@|%]/.test(text)) {
        return csvCell(`'${text}`);
    }
    return csvCell(text);
}

/** Descarga un resumen fiscal (reporte + posiciones) como CSV generado en cliente */
function downloadTaxSummary(holdings: DataRecord[], report: DataRecord | null, year: number) {
    const lines: string[] = [`reporte_fiscal,${year}`, ''];
    lines.push('seccion,clave,valor');
    if (report) {
        for (const [key, value] of Object.entries(report)) {
            lines.push(`reporte,${csvExportCell(key)},${csvExportCell(value)}`);
        }
    } else {
        lines.push('reporte,sin_reporte,Sin reporte fiscal disponible');
    }
    lines.push('');
    if (holdings.length > 0) {
        const headers = Array.from(
            new Set(holdings.flatMap((holding) => Object.keys(holding))),
        ).slice(0, 12);
        lines.push(headers.map(csvExportCell).join(','));
        for (const holding of holdings) {
            lines.push(
                headers.map((header) => csvExportCell(holding[header])).join(','),
            );
        }
    }
    const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `resumen-fiscal-${year}.csv`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
}

export default function TaxesView({ initialHoldings, initialReport, initialThresholds720, initialFile720, initialThresholds720Unavailable, year }: TaxesViewProps) {
    const router = useRouter();
    const [regenerating, setRegenerating] = useState(false);
    // F260: el informe mostrado se DERIVA del año pedido (reportForYear), no
    // se copia a un estado espejo. Un useState(initialReport) + useEffect de
    // resync dejaba un render intermedio con el informe viejo: RecordDetail se
    // remontaba (key con year) capturando ese informe viejo, y el título
    // decía «Reporte Fiscal 2025» con el contenido de 2026. Solo se guarda el
    // override de «Regenerar», etiquetado con su ejercicio.
    const [override, setOverride] = useState<ReportOverride | null>(null);
    const [reportKey, setReportKey] = useState(0);
    const [holdingPage, setHoldingPage] = useState(0);
    const holdingPages = Math.max(1, Math.ceil(initialHoldings.length / 10));
    const currentHoldingPage = Math.min(holdingPage, holdingPages - 1);
    const report = reportForYear(override, initialReport, year);
    const staleNotice = staleReportNotice(report);

    const handleYearChange = (next: string) => {
        const parsed = Number.parseInt(next, 10);
        if (!Number.isInteger(parsed)) return;
        setHoldingPage(0);
        router.push(`/taxes?year=${parsed}`);
    };

    const handleRegenerate = async () => {
        setRegenerating(true);
        try {
            await regenerateTaxReport(year);
            // Recarga el reporte recien regenerado (POST regenerate) para que
            // la vista muestre los datos nuevos sin recarga manual.
            const fresh = (await getTaxReport(year).catch(() => null)) as DataRecord | null;
            if (fresh) {
                setOverride({ year, report: fresh });
                setReportKey((key) => key + 1);
            } else {
                setOverride(null);
                router.refresh();
            }
            toast.success(`Reporte fiscal ${year} regenerado`);
        } catch (error) {
            showErrorToast(error, { onRetry: handleRegenerate });
        } finally {
            setRegenerating(false);
        }
    };

    // El año civil viene del reloj del navegador: leerlo en el render rompe la
    // hidratación en la frontera de año. Se arranca con un estado fijo (0) y se
    // fija el año real en el primer efecto.
    const currentYear = useSyncExternalStore(
        () => () => {},
        // Año civil del usuario (Europe/Madrid), igual que el servidor en taxes/page.tsx.
        () => Number(new Intl.DateTimeFormat('en-CA', { timeZone: USER_TZ, year: 'numeric' }).format(new Date())),
        () => 0,
    );
    const yearOptions = currentYear === 0
        ? []
        : Array.from({ length: 6 }, (_, index) => currentYear - index);

    // [&>*]:min-w-0: a 768 px (md) la tarjeta «Posiciones Fiscales» (min-content
    // 513 px) inflaba la vía implícita de esta grid y la página hacía scroll
    // horizontal; con min-w-0 cada tarjeta cabe y su tabla desliza dentro.
    return (
        <div className="grid gap-6 [&_a.font-mono]:inline-flex [&_a.font-mono]:min-h-11 [&_a.font-mono]:items-center [&>*]:min-w-0">
            <div className="flex flex-wrap items-center gap-3">
                <label htmlFor="tax-year" className="text-sm text-gray-400">
                    {t('taxes.year')}
                </label>
                <select
                    id="tax-year"
                    value={year}
                    onChange={(event) => handleYearChange(event.target.value)}
                    className="h-11 rounded-md border border-gray-800 bg-black px-3 text-sm text-gray-200"
                >
                    {yearOptions.map((option) => (
                        <option key={option} value={option}>
                            {option}
                        </option>
                    ))}
                </select>
            </div>
            {staleNotice ? (
                <div
                    role="status"
                    data-testid="stale-report-notice"
                    className="flex flex-wrap items-center gap-3 rounded-lg border border-amber-900/60 bg-amber-950/20 p-3 text-sm text-amber-200"
                >
                    <span className="min-w-0 flex-1">{staleNotice}</span>
                    <Button size="sm" variant="outline" onClick={handleRegenerate} disabled={regenerating}>
                        Regenerar ahora
                    </Button>
                </div>
            ) : null}
            <RecordDetail
                key={recordDetailKey(year, reportKey)}
                title={`Reporte Fiscal ${year}`}
                titleAs="h2"
                description="Resumen orientativo del ejercicio"
                icon={<FileText className="h-5 w-5 text-teal-400" />}
                hiddenKeys={['trace']}
                record={toDisplayReport(report)}
                fetchRecord={async () => toDisplayReport((await getTaxReport(year)) as DataRecord | null)}
                emptyMessage={t('taxes.noReport')}
                actions={
                    <Button
                        size="sm"
                        variant="outline"
                        onClick={handleRegenerate}
                        disabled={regenerating}
                        className="gap-2 border-gray-600 text-gray-300 hover:text-teal-400"
                    >
                        <RotateCcw className={`h-4 w-4 ${regenerating ? 'animate-spin' : ''}`} />
                        {t('taxes.regenerate')}
                    </Button>
                }
            />

            <FilingSection key={`filing-${year}-${reportKey}`} filing={(report?.filing as DataRecord | undefined) ?? null}
                year={year} onPreview={(fresh) => setOverride({ year, report: fresh })}
                onReset={() => setOverride(null)} />

            <Modelo720Section thresholds={initialThresholds720} file720={initialFile720} unavailable={initialThresholds720Unavailable} />

            <RecordList
                key={`holdings-${year}-${currentHoldingPage}`}
                title="Posiciones Fiscales"
                titleAs="h2"
                description="Posiciones con base de coste y plusvalías latentes. La divisa base del informe es EUR; cada importe usa la divisa de su fila si consta."
                icon={<Receipt className="h-5 w-5 text-teal-400" />}
                records={initialHoldings.slice(currentHoldingPage * 10, (currentHoldingPage + 1) * 10)}
                fetchRecords={async () => (await getTaxHoldings()).slice(currentHoldingPage * 10, (currentHoldingPage + 1) * 10)}
                columns={['ticker', 'quantity', 'cost_basis', 'market_value', 'unrealized_pnl']}
                columnLabels={{
                    ticker: 'Ticker',
                    quantity: 'Cantidad',
                    cost_basis: 'Base de coste',
                    market_value: 'Valor de mercado',
                    unrealized_pnl: 'Plusvalía latente',
                    currency: 'Divisa',
                }}
                emptyMessage="Aún no hay posiciones con datos fiscales. Cuando compres valores aparecerán aquí."
                formatColumns={Object.fromEntries([
                    // Cantidades fraccionadas (IBKR) con separadores es-ES:
                    // «6.0572» crudo -> «6,0572». Hasta 6 decimales reales.
                    ['quantity', (value: unknown) => formatNumber(value as number | string, { maximumFractionDigits: 6 })],
                    ...TAX_HOLDING_MONEY_COLUMNS.map((column) => [
                        column,
                        (value: unknown, record: DataRecord) => formatHoldingCell(column, value, record),
                    ]),
                ])}
                linkColumns={{ ticker: (record) => researchHrefFor(record) }}
                footer={
                    <Button
                        size="sm"
                        variant="outline"
                        onClick={() => {
                            downloadTaxSummary(initialHoldings, report, year);
                            toast.success(`Resumen fiscal ${year} exportado`);
                        }}
                        disabled={initialHoldings.length === 0 && !report}
                        className="gap-2 border-gray-600 text-gray-300 hover:text-teal-400"
                    >
                        <Download className="h-4 w-4" />
                        Exportar resumen
                    </Button>
                }
            />
            {holdingPages > 1 && <nav aria-label="Páginas de posiciones fiscales" className="flex items-center justify-between gap-2">
                <Button size="sm" variant="outline" disabled={currentHoldingPage === 0} onClick={() => setHoldingPage(currentHoldingPage - 1)}>Anterior</Button>
                <span className="text-xs text-gray-400">{currentHoldingPage + 1} / {holdingPages} · {formatCountEs(initialHoldings.length, 'posición', 'posiciones')}</span>
                <Button size="sm" variant="outline" disabled={currentHoldingPage + 1 >= holdingPages} onClick={() => setHoldingPage(currentHoldingPage + 1)}>Siguiente</Button>
            </nav>}
        </div>
    );
}
