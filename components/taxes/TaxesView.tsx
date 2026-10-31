'use client';

import { useState, useSyncExternalStore } from 'react';
import Link from 'next/link';
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
import { formatMoney, formatNumber, isValidCurrencyCode, USER_TZ } from '@/lib/format';
import { t } from '@/lib/i18n/t';
import { useT, useFormat } from '@/lib/i18n/client';
import type { TranslateFn as TFunction } from '@/lib/i18n/translate';
import type { Formatters } from '@/lib/format';
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

/** Contexto de copy y formato ligado al locale activo: las funciones puras
 *  de abajo no pueden llamar hooks, así que la vista se lo inyecta. */
type TaxI18n = { t: TFunction; f: Formatters };

/** El endpoint envuelve las métricas en {summary, dividends, realized, misc}:
 *  para mostrarlas se aplana `summary` (métricas fiscales legibles) y se
 *  conserva generated_at; las listas crudas no se pintan como JSON. */
function toDisplayReport(raw: DataRecord | null, i18n: TaxI18n): DataRecord | null {
    if (!raw || typeof raw !== 'object') return null;
    const summary = raw.summary;
    if (summary === null || typeof summary !== 'object' || Array.isArray(summary)) return raw;
    const display: DataRecord = { ...(summary as DataRecord) };
    if (raw.generated_at) display.generated_at = raw.generated_at;
    const humanized = humanizeTaxReport(display, i18n);
    // F183: sin `generated_at` y con `persisted=false` el informe se
    // calculó al vuelo y no está guardado: la fila «Generado» lo declara
    // en lugar de simplemente no existir.
    const onTheFly = onTheFlyReportNote(raw) ? i18n.t('taxes.values.onTheFlyNote') : null;
    if (onTheFly) humanized[i18n.t('taxes.labels.generatedAt')] = onTheFly;
    return humanized;
}

/** Aviso de informe guardado con un criterio de cálculo anterior. Sale del
 *  bloque `versioning` que calcula el backend (tax_report_versioning.py): la UI
 *  no decide nada, solo lo muestra. Sin `versioning` (backend antiguo) o con
 *  `stale` distinto de true no hay aviso. */
function staleReportNotice(raw: DataRecord | null, tFn: TFunction): string | null {
    const versioning = raw?.versioning;
    if (!versioning || typeof versioning !== 'object' || Array.isArray(versioning)) return null;
    if ((versioning as DataRecord).stale !== true) return null;
    const outdated = (versioning as DataRecord).outdated;
    const markers = Array.isArray(outdated) ? outdated : [];
    const missing = markers.some((item) => (item as DataRecord | null)?.reason === 'criterio_no_registrado');
    const why = missing
        ? tFn('taxes.stale.reasonUnregistered')
        : tFn('taxes.stale.reasonOutdated');
    return tFn('taxes.stale.notice', { why });
}

/** Claves conocidas del resumen fiscal (F20) -> clave del diccionario i18n.
 *  Las claves desconocidas se humanizan (snake_case -> frase) sin ocultarse. */
const TAX_LABEL_KEYS: Record<string, string> = {
    fiscal_year: 'taxes.labels.fiscalYear',
    base_currency: 'taxes.labels.baseCurrency',
    total_dividends_base: 'taxes.labels.totalDividendsBase',
    total_withholding_base: 'taxes.labels.totalWithholdingBase',
    total_realized_gain_base: 'taxes.labels.totalRealizedGainBase',
    total_blocked_loss_base: 'taxes.labels.totalBlockedLossBase',
    net_taxable_base: 'taxes.labels.netTaxableBase',
    wash_sale_rule: 'taxes.labels.washSaleRule',
    wash_sale_basis: 'taxes.labels.washSaleBasis',
    fiscal_disclaimer: 'taxes.labels.fiscalDisclaimer',
    wash_sale_window_open: 'taxes.labels.washSaleWindowOpen',
    dividend_count: 'taxes.labels.dividendCount',
    sell_count: 'taxes.labels.sellCount',
    over_sell: 'taxes.labels.overSell',
    cost_unknown: 'taxes.labels.costUnknown',
    method: 'taxes.labels.method',
    securities_fx_criterion: 'taxes.labels.securitiesFxCriterion',
    currency_ledger_criterion: 'taxes.labels.currencyLedgerCriterion',
    currency_ledger_status: 'taxes.labels.currencyLedgerStatus',
    currency_ledger_gain_base: 'taxes.labels.currencyLedgerGainBase',
    currency_ledger_reason: 'taxes.labels.currencyLedgerReason',
    currency_ledger_blocked_loss_base: 'taxes.labels.currencyLedgerBlockedLossBase',
    currency_ledger_note: 'taxes.labels.currencyLedgerNote',
    currency_ledger_by_currency: 'taxes.labels.currencyLedgerByCurrency',
    incomplete_fx: 'taxes.labels.incompleteFx',
    missing_fx: 'taxes.labels.missingFx',
    generated_at: 'taxes.labels.generatedAt',
    unattributed_tickers: 'taxes.labels.unattributedTickers',
    unattributed_dividends_base: 'taxes.labels.unattributedDividendsBase',
    inconsistent_cash_rows: 'taxes.labels.inconsistentCashRows',
    zero_cost_buys: 'taxes.labels.zeroCostBuys',
    ambiguous_cash: 'taxes.labels.ambiguousCash',
    manual_review: 'taxes.labels.manualReview',
};

function humanizeKey(key: string, tFn: TFunction): string {
    const known = TAX_LABEL_KEYS[key];
    if (known) return tFn(known as Parameters<TFunction>[0]);
    const words = key.replaceAll('_', ' ').trim();
    return words.charAt(0).toUpperCase() + words.slice(1);
}

/** El backend etiqueta el efectivo sin compañía resuelta como
 *  `UNATTRIBUTED:SIMBOLO` (o `UNATTRIBUTED:DIVISA:ACCION` cuando ni eso se
 *  recuperó). Es un identificador interno estable, no copy de UI: aquí se
 *  traduce conservando el símbolo, que es la parte útil. */
function humanizeUnattributedTicker(item: string, tFn: TFunction): string {
    const match = /^UNATTRIBUTED:(.+)$/.exec(item);
    if (!match) return item;
    return tFn('taxes.values.unattributed', { symbol: match[1] });
}

/** Filas de caja inconsistentes del resumen: el importe es un CANDIDATO
 *  (price x quantity no canónica), nunca un pago medido; se lista legible
 *  para su revisión manual en vez de volcarse como objeto crudo. */
function formatInconsistentCashRows(value: unknown, i18n: TaxI18n): string {
    if (!Array.isArray(value) || value.length === 0) return i18n.t('taxes.values.noneF');
    return (value as DataRecord[]).map((row) => {
        const ticker = typeof row.ticker === 'string' && row.ticker ? row.ticker : i18n.t('common.na');
        const date = typeof row.date === 'string' && row.date ? row.date : i18n.t('common.na');
        const action = typeof row.action === 'string' && row.action ? row.action : i18n.t('common.na');
        // Una divisa ausente o rara NUNCA se sustituye (regla de lib/format):
        // sin divisa válida el importe se omite, no se etiqueta como EUR.
        const code = typeof row.currency === 'string' ? row.currency.trim().toUpperCase() : '';
        const currency = isValidCurrencyCode(code) ? code : null;
        const amount = row.amount === null || row.amount === undefined || currency === null
            ? null
            : `${i18n.f.formatMoney(row.amount as number | string, currency)} ${i18n.t('taxes.values.candidate')}`;
        return [ticker, date, action, amount].filter((part) => part !== null).join(' · ');
    }).join(' | ');
}

/** Convierte el resumen fiscal a filas etiquetadas con valores formateados
 *  (importes con divisa, listas de tickers, fechas). Nunca inventa: los null
 *  quedan como `NA` («N/D») y las claves raras se humanizan. */
function humanizeTaxReport(summary: DataRecord, i18n: TaxI18n): DataRecord {
    const tFn = i18n.t;
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
        overSold.length > 0 ? tFn('taxes.values.reasonOversell', { tickers: overSold.join(', ') }) : null,
        costUnknown.length > 0
            ? tFn('taxes.values.reasonCostUnknown', { tickers: costUnknown.join(', ') })
            : null,
        ambiguousCash ? tFn('taxes.values.reasonAmbiguousCash') : null,
        missingFx ? tFn('taxes.values.reasonMissingFx') : null,
    ].filter(Boolean).join(tFn('taxes.values.reasonJoin'));
    const nullLabel = nullReason ? `${i18n.t('common.na')} (${nullReason})` : i18n.t('common.na');
    const display: DataRecord = {};
    for (const [key, value] of Object.entries(summary)) {
        const label = humanizeKey(key, tFn);
        if (moneyKeys.has(key)) {
            display[label] = value === null || value === undefined
                ? nullLabel
                : i18n.f.formatMoney(value as number | string, currency);
        } else if (listKeys.has(key)) {
            display[label] = Array.isArray(value) && value.length > 0
                ? value.map((item) => humanizeUnattributedTicker(String(item), tFn)).join(', ')
                : tFn('taxes.values.noneM');
        } else if (key === 'inconsistent_cash_rows') {
            display[label] = formatInconsistentCashRows(value, i18n);
        } else if (key === 'zero_cost_buys') {
            // Compras a precio 0 (regalo / spin-off): aceptadas, pero a revisar.
            const rows = Array.isArray(value) ? (value as DataRecord[]) : [];
            display[label] = rows.length > 0
                ? rows.map((row) => `${String(row.ticker)} ${String(row.date)} · ${String(row.label ?? tFn('taxes.values.zeroCostDefault'))}`).join(' · ')
                : tFn('taxes.values.noneF');
        } else if (key === 'wash_sale_rule') {
            display[label] = ({ 'es-irpf-2m': tFn('taxes.values.washRuleEsIrpf2m') } as Record<string, string>)[String(value)] ?? String(value);
        } else if (key === 'wash_sale_basis') {
            display[label] = ({ 'manual-aeat-2025': tFn('taxes.values.washBasisManualAeat2025') } as Record<string, string>)[String(value)] ?? String(value);
        } else if (key === 'securities_fx_criterion') {
            display[label] = ({ dgt_native_gain_sale_date_v1: tFn('taxes.values.securitiesFxDgt') } as Record<string, string>)[String(value)] ?? String(value);
        } else if (key === 'currency_ledger_status') {
            display[label] = ({
                not_computed: tFn('taxes.ledger.notComputed'),
                incomplete: tFn('taxes.ledger.incomplete'),
                computed: tFn('taxes.ledger.computed'),
            } as Record<string, string>)[String(value)] ?? String(value);
        } else if (key === 'currency_ledger_gain_base' || key === 'currency_ledger_blocked_loss_base') {
            // Importe fiscal en EUR: formateado es-ES como el resto de
            // importes; un float crudo («1234.5678») no es una cifra legible.
            display[label] = value === null || value === undefined ? tFn('taxes.ledger.notComputed') : formatMoney(value as number | string, currency);
        } else if (key === 'currency_ledger_by_currency') {
            const byCurrency = (value ?? {}) as Record<string, { status?: string; gain_base?: number | null; unconverted?: number | null }>;
            const names: Record<string, string> = {
                not_computed: tFn('taxes.ledger.notComputed'),
                incomplete: tFn('taxes.ledger.incomplete'),
                computed: tFn('taxes.ledger.computed'),
            };
            const parts = Object.entries(byCurrency).map(([cur, v]) => `${cur}: ${v.gain_base === null || v.gain_base === undefined ? tFn('taxes.ledger.notComputed') : formatMoney(v.gain_base, 'EUR')} (${names[String(v.status)] ?? String(v.status)}${v.unconverted === null || v.unconverted === undefined ? '' : `, ${tFn('taxes.ledger.unconverted', { amount: formatNumber(v.unconverted, { maximumFractionDigits: 2 }), currency: cur })}`})`);
            display[label] = parts.length > 0 ? parts.join(' · ') : tFn('taxes.ledger.noConversions');
        } else if (key === 'currency_ledger_reason') {
            display[label] = value ?? tFn('taxes.values.noneM');
        } else if (key === 'method') {
            display[label] = ({ fifo: tFn('taxes.values.methodFifo') } as Record<string, string>)[String(value).toLowerCase()] ?? String(value);
        } else if (key === 'generated_at') {
            display[label] = i18n.f.formatUserDateTime(value as string);
        } else if (typeof value === 'boolean') {
            display[label] = value ? tFn('taxes.values.yes') : tFn('taxes.values.no');
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
function csvFullValue(value: unknown, tFn: TFunction, depth = 8): string {
    if (value === null || value === undefined) return '—';
    if (typeof value === 'boolean') return value ? tFn('taxes.values.yes') : tFn('taxes.values.no');
    if (typeof value === 'number') return String(value);
    if (typeof value === 'string') return value;
    if (value instanceof Date) return value.toISOString();
    if (depth <= 0) return JSON.stringify(value);
    if (Array.isArray(value)) {
        if (value.length === 0) return '—';
        return value.map((item) => csvFullValue(item, tFn, depth - 1)).join(' · ');
    }
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) return '—';
    return entries
        .map(([key, item]) => `${humanizeKey(key, tFn)}: ${csvFullValue(item, tFn, depth - 1)}`)
        .join(' · ');
}

/** Neutraliza fórmulas de hoja de cálculo (convención `_csv_cell` del
 *  backend, export.py): si el valor ORIGINAL es texto y empieza por
 *  = + - @ | %, la celda lleva prefijo '. Un número negativo (-10) queda
 *  intacto: las hojas ya lo parsean como número; una cadena '-10' sí se
 *  neutraliza, igual que el backend (isinstance str). Las comillas de
 *  csvCell solo protegen la estructura del CSV, no la interpretación
 *  como fórmula. */
function csvExportCell(value: unknown, tFn: TFunction): string {
    const text = csvFullValue(value, tFn);
    if (typeof value === 'string' && /^[=+\-@|%]/.test(text)) {
        return csvCell(`'${text}`);
    }
    return csvCell(text);
}

/** Descarga un resumen fiscal (informe + posiciones) como CSV generado en cliente */
function downloadTaxSummary(holdings: DataRecord[], report: DataRecord | null, year: number, tFn: TFunction) {
    const lines: string[] = [`informe_fiscal,${year}`, ''];
    lines.push('seccion,clave,valor');
    if (report) {
        for (const [key, value] of Object.entries(report)) {
            lines.push(`informe,${csvExportCell(key, tFn)},${csvExportCell(value, tFn)}`);
        }
    } else {
        lines.push(`informe,sin_informe,${tFn('taxes.csv.noReport')}`);
    }
    lines.push('');
    if (holdings.length > 0) {
        const headers = Array.from(
            new Set(holdings.flatMap((holding) => Object.keys(holding))),
        ).slice(0, 12);
        lines.push(headers.map((header) => csvExportCell(header, tFn)).join(','));
        for (const holding of holdings) {
            lines.push(
                headers.map((header) => csvExportCell(holding[header], tFn)).join(','),
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

/** Ejercicio sin actividad: informe con listas vacías (no ausentes) y sin posiciones. */
function isEmptyTaxYear(report: unknown, holdings: readonly unknown[]): boolean {
    if (holdings.length > 0 || !report || typeof report !== 'object') return false;
    const r = report as Record<string, unknown>;
    return ['dividends', 'realized', 'misc'].every((key) => Array.isArray(r[key]) && (r[key] as unknown[]).length === 0);
}

export default function TaxesView({ initialHoldings, initialReport, initialThresholds720, initialFile720, initialThresholds720Unavailable, year }: TaxesViewProps) {
    const router = useRouter();
    const ti = useT();
    const f = useFormat();
    const i18n: TaxI18n = { t: ti, f };
    const [regenerating, setRegenerating] = useState(false);
    // F260: el informe mostrado se DERIVA del año pedido (reportForYear), no
    // se copia a un estado espejo. Un useState(initialReport) + useEffect de
    // resync dejaba un render intermedio con el informe viejo: RecordDetail se
    // remontaba (key con year) capturando ese informe viejo, y el título
    // decía «Informe fiscal 2025» con el contenido de 2026. Solo se guarda el
    // override de «Regenerar», etiquetado con su ejercicio.
    const [override, setOverride] = useState<ReportOverride | null>(null);
    const [reportKey, setReportKey] = useState(0);
    const [holdingPage, setHoldingPage] = useState(0);
    const holdingPages = Math.max(1, Math.ceil(initialHoldings.length / 10));
    const currentHoldingPage = Math.min(holdingPage, holdingPages - 1);
    const report = reportForYear(override, initialReport, year);
    const staleNotice = staleReportNotice(report, ti);
    const emptyYear = isEmptyTaxYear(report, initialHoldings);

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
            toast.success(ti('taxes.toastRegenerated', { year }));
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

    // [&>*]:min-w-0: a 768 px (md) la tarjeta «Posiciones fiscales» (min-content
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
                        {ti('taxes.stale.regenerateNow')}
                    </Button>
                </div>
            ) : null}
            {emptyYear ? (
                <div
                    role="status"
                    data-testid="empty-tax-year"
                    className="rounded-lg border border-gray-800 bg-surface-1 p-4 text-sm text-gray-300"
                >
                    <p>{ti('taxes.emptyYear.message', { year })}</p>
                    <div className="mt-3 flex flex-wrap gap-2">
                        <Link href="/portfolio?anadir=1" className="inline-flex min-h-11 items-center rounded-lg bg-teal-400/10 px-3 font-medium text-teal-300 hover:bg-teal-400/20">
                            {ti('taxes.emptyYear.addInvestment')}
                        </Link>
                        <Link href="/settings" className="inline-flex min-h-11 items-center rounded-lg px-3 font-medium text-gray-300 hover:bg-gray-800 hover:text-gray-100">
                            {ti('taxes.emptyYear.connectIbkr')}
                        </Link>
                    </div>
                </div>
            ) : null}
            <RecordDetail
                key={recordDetailKey(year, reportKey)}
                title={ti('taxes.report.title', { year })}
                titleAs="h2"
                description={ti('taxes.report.description')}
                icon={<FileText className="h-5 w-5 text-teal-400" />}
                hiddenKeys={['trace']}
                record={toDisplayReport(report, i18n)}
                fetchRecord={async () => toDisplayReport((await getTaxReport(year)) as DataRecord | null, i18n)}
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
                title={ti('taxes.holdings.title')}
                titleAs="h2"
                description={ti('taxes.holdings.description')}
                icon={<Receipt className="h-5 w-5 text-teal-400" />}
                records={initialHoldings.slice(currentHoldingPage * 10, (currentHoldingPage + 1) * 10)}
                fetchRecords={async () => (await getTaxHoldings()).slice(currentHoldingPage * 10, (currentHoldingPage + 1) * 10)}
                columns={['ticker', 'quantity', 'cost_basis', 'market_value', 'unrealized_pnl']}
                columnLabels={{
                    ticker: ti('taxes.holdings.ticker'),
                    quantity: ti('taxes.holdings.quantity'),
                    cost_basis: ti('taxes.holdings.costBasis'),
                    market_value: ti('taxes.holdings.marketValue'),
                    unrealized_pnl: ti('taxes.holdings.unrealizedPnl'),
                    currency: ti('taxes.holdings.currency'),
                }}
                emptyMessage={ti('taxes.holdings.empty')}
                formatColumns={Object.fromEntries([
                    // Cantidades fraccionadas (IBKR) con separadores del
                    // locale activo: «6.0572» crudo -> «6,0572» en es-ES.
                    // Hasta 6 decimales reales.
                    ['quantity', (value: unknown) => f.formatNumber(value as number | string, { maximumFractionDigits: 6 })],
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
                            downloadTaxSummary(initialHoldings, report, year, ti);
                            toast.success(ti('taxes.toastExported', { year }));
                        }}
                        disabled={initialHoldings.length === 0 && !report}
                        className="gap-2 border-gray-600 text-gray-300 hover:text-teal-400"
                    >
                        <Download className="h-4 w-4" />
                        {ti('taxes.holdings.export')}
                    </Button>
                }
            />
            {holdingPages > 1 && <nav aria-label={ti('taxes.holdings.navAria')} className="flex items-center justify-between gap-2">
                <Button size="sm" variant="outline" disabled={currentHoldingPage === 0} onClick={() => setHoldingPage(currentHoldingPage - 1)}>{ti('taxes.holdings.prev')}</Button>
                <span className="text-xs text-gray-400">{currentHoldingPage + 1} / {holdingPages} · {f.formatCount(initialHoldings.length, ti('taxes.holdings.position'), ti('taxes.holdings.positionPlural'))}</span>
                <Button size="sm" variant="outline" disabled={currentHoldingPage + 1 >= holdingPages} onClick={() => setHoldingPage(currentHoldingPage + 1)}>{ti('taxes.holdings.next')}</Button>
            </nav>}
        </div>
    );
}
