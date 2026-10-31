'use client';

import Link from 'next/link';
import { useState } from 'react';
import { RecordList } from '@/components/data/RecordViews';
import TmePreviewForm from '@/components/taxes/TmePreviewForm';
import { useT, useFormat } from '@/lib/i18n/client';
import type { TranslateFn as TFunction } from '@/lib/i18n/translate';
import type { Formatters } from '@/lib/format';
import { Landmark, FileDown, AlertTriangle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { humanizeTaxText } from '@/lib/taxes/humanize-text';
import { filingSectionKey } from '@/lib/taxes/section-keys';

/**
 * Secciones de declaración de la página Impuestos (Modelo 100 + Modelo 720).
 *
 * Cohesión: misma gramática visual que el resto de la vista (paneles con
 * borde gray-800, acentos teal). Honestidad: todo número viene del backend;
 * los estados sin datos se declaran (available=false, tri-estado
 * «desconocido», badges «estimativo») y nunca se presenta nada como listo
 * para declarar.
 */

type DataRecord = Record<string, unknown>;

function money(value: unknown, f: Formatters, t: TFunction): string {
    if (value === null || value === undefined) return t('common.na');
    return f.formatMoney(value as number | string, 'EUR');
}

/**
 * Descarga el fichero 720 tal cual lo genera el backend.
 *
 * El backend lo devuelve ya en ISO-8859-1 (spec AEAT) y saneado a caracteres
 * latin-1, así que cada carácter es un byte: se reconstruye el Uint8Array con
 * `charCodeAt & 0xff` en vez de dejar que el navegador lo guarde en UTF-8 y
 * corrompa el diseño de 500 bytes por registro.
 */
function downloadFile720(content: string, fileName: string) {
    const bytes = new Uint8Array(content.length);
    for (let index = 0; index < content.length; index += 1) {
        bytes[index] = content.charCodeAt(index) & 0xff;
    }
    const url = URL.createObjectURL(new Blob([bytes], { type: 'application/octet-stream' }));
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = fileName;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
}

function Section({ title, description, icon, children }: {
    title: string;
    description: string;
    icon: React.ReactNode;
    children: React.ReactNode;
}) {
    return (
        <section className="rounded-lg border border-gray-800 bg-gray-950/40 p-5">
            <header className="mb-4 flex items-start gap-3">
                <span className="mt-0.5">{icon}</span>
                <div>
                    <h2 className="text-lg font-semibold text-gray-100">{title}</h2>
                    <p className="mt-1 text-sm leading-6 text-gray-400">{description}</p>
                </div>
            </header>
            {children}
        </section>
    );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
    return (
        <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-gray-800/60 py-2 text-sm last:border-0">
            <span className="text-gray-400">{label}</span>
            <span className="text-right text-gray-200">{value}</span>
        </div>
    );
}

const CHIP_CLASS: Record<string, string> = {
    supera: 'border-amber-700 text-amber-300',
    por_debajo: 'border-teal-800 text-teal-300',
    desconocido: 'border-gray-600 text-gray-300',
    no_evaluable: 'border-gray-700 text-gray-500',
};

const CHIP_LABEL_KEYS: Record<string, Parameters<TFunction>[0]> = {
    supera: 'taxes.modelo720.chipSupera',
    por_debajo: 'taxes.modelo720.chipPorDebajo',
    desconocido: 'taxes.modelo720.chipDesconocido',
    no_evaluable: 'taxes.modelo720.chipNoEvaluable',
};

function Chip({ status }: { status: string }) {
    const t = useT();
    const known = CHIP_LABEL_KEYS[status] ? status : 'desconocido';
    return (
        <span className={`inline-block rounded-full border px-2 py-0.5 text-xs ${CHIP_CLASS[known]}`}>
            {t(CHIP_LABEL_KEYS[known])}
        </span>
    );
}

function percent(value: unknown, f: Formatters, t: TFunction): string {
    return typeof value === 'number' && Number.isFinite(value)
        ? f.formatPercent(value, { digits: 2 })
        : t('common.na');
}

/**
 * Desglose de la casilla 0588 por país (A15, criterio de Hacienda): para
 * cada país, el menor entre la retención con tope del convenio y el TME del
 * ahorro aplicado al dividendo ÍNTEGRO. Sin TME no se inventa el límite.
 */
function DoubleTaxationByCountry({ countries }: { countries: DataRecord[] }) {
    const t = useT();
    const f = useFormat();
    if (countries.length === 0) return null;
    return (
        <div className="mt-3 space-y-1 text-xs leading-5 text-gray-400">
            <p>{t('taxes.filing.doubleTaxation.limitNote')}</p>
            <ul aria-label={t('taxes.filing.doubleTaxation.listAria')} className="space-y-1">
                {countries.map((c) => {
                    const tmeLimit = c.tme_limit_base == null
                        ? t('taxes.filing.doubleTaxation.tmeMissing')
                        : money(c.tme_limit_base, f, t);
                    const applied = c.limit_applied === 'bruto_x_tme'
                        ? t('taxes.filing.doubleTaxation.appliedGross')
                        : c.limit_applied === 'tope_convenio' ? t('taxes.filing.doubleTaxation.appliedTreaty') : '';
                    return (
                        <li key={String(c.country)}>
                            {t('taxes.filing.doubleTaxation.row', {
                                country: String(c.country),
                                gross: money(c.gross_base, f, t),
                                withheld: money(c.withheld_base, f, t),
                                rate: percent(c.treaty_rate, f, t),
                                cap: money(c.treaty_cap_base, f, t),
                                tme: tmeLimit,
                                deduction: c.deduction_base == null ? t('common.na') : money(c.deduction_base, f, t),
                                applied,
                            })}
                        </li>
                    );
                })}
            </ul>
        </div>
    );
}

function WarningList({ items }: { items: string[] }) {
    if (items.length === 0) return null;
    return (
        <ul className="mt-3 space-y-1 text-xs leading-5 text-amber-200/80">
            {items.map((item) => (
                <li key={item} className="flex gap-2">
                    <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    <span>{humanizeTaxText(item)}</span>
                </li>
            ))}
        </ul>
    );
}

export function FilingSection({ filing, year, onPreview, onReset }: {
    filing: DataRecord | null;
    year: number;
    onPreview: (report: DataRecord) => void;
    onReset: () => void;
}) {
    const t = useT();
    const f = useFormat();
    if (!filing) return (
        <Section title={t('taxes.filing.title')} description={t('taxes.filing.descHelp')}
            icon={<Landmark className="h-5 w-5 text-teal-400" />}>
            <p className="text-sm text-gray-400">{t('taxes.filing.ndGenerate')}</p>
        </Section>
    );
    if (filing.available === false) {
        return (
            <Section
                title={t('taxes.filing.title')}
                description={t('taxes.filing.descBoxes')}
                icon={<Landmark className="h-5 w-5 text-teal-400" />}
            >
                {/* El backend explica el bloqueo (hoy: la cartera no usa EUR
                    como divisa base). El texto de reserva NO dice «no
                    disponible»: dice qué se necesita para que se pueda calcular. */}
                <p className="text-sm text-gray-400">
                    {typeof filing.reason === 'string' && filing.reason
                        ? humanizeTaxText(filing.reason)
                        : t('taxes.filing.fallbackReason')}
                </p>
            </Section>
        );
    }
    const casillas = (filing.casillas ?? {}) as DataRecord;
    if (casillas.available === false) {
        return (
            <Section
                title={t('taxes.filing.title')}
                description={t('taxes.filing.descBoxes')}
                icon={<Landmark className="h-5 w-5 text-teal-400" />}
            >
                <p className="text-sm text-gray-400">
                    {typeof casillas.unavailable_reason === 'string' && casillas.unavailable_reason
                        ? humanizeTaxText(casillas.unavailable_reason)
                        : t('taxes.filing.fallbackBoxes')}
                </p>
            </Section>
        );
    }
    if (filing.available !== true || casillas.available !== true) return (
        <Section title={t('taxes.filing.title')} description={t('taxes.filing.descHelp')}
            icon={<Landmark className="h-5 w-5 text-teal-400" />}>
            <p className="text-sm text-gray-400">{t('taxes.filing.ndUnconfirmed')}</p>
        </Section>
    );
    const acciones = (casillas.acciones_negociadas ?? {}) as DataRecord;
    const dividendos = (casillas.dividendos ?? {}) as DataRecord;
    const dt = (filing.double_taxation ?? {}) as DataRecord;
    const lc = (filing.loss_compensation ?? {}) as DataRecord;
    const intereses = (filing.intereses ?? {}) as {
        received?: { amount_base?: number | null };
        margin_interest_paid?: { amount_base?: number | null };
    };
    const manualReview = Array.isArray(dt.manual_review) ? dt.manual_review as DataRecord[] : [];
    const specialTickers = Array.isArray(dividendos.special_payment_tickers)
        ? dividendos.special_payment_tickers as string[]
        : [];
    const warnings: string[] = [
        ...manualReview.map((item) => `${humanizeTaxText(String(item.ticker ?? ''))}: ${humanizeTaxText(String(item.reason ?? ''))}`),
        ...(specialTickers.length > 0
            ? [t('taxes.filing.specialPayments', { tickers: specialTickers.join(', ') })]
            : []),
    ];
    return (
        <Section
            title={t('taxes.filing.title')}
            description={t('taxes.filing.descBoxesFull')}
            icon={<Landmark className="h-5 w-5 text-teal-400" />}
        >
            <div className="grid gap-1">
                <Row label={t('taxes.filing.row0328')} value={money(acciones['0328_transmision_global'], f, t)} />
                <Row label={t('taxes.filing.row0331')} value={money(acciones['0331_adquisicion_global'], f, t)} />
                <Row label={t('taxes.filing.row0339')} value={money(acciones['0339_suma_ganancias'], f, t)} />
                <Row label={t('taxes.filing.row0340')} value={money(acciones['0340_suma_perdidas'], f, t)} />
                <Row label={t('taxes.filing.row0029')} value={money(dividendos['0029_ingresos_integros'], f, t)} />
                <Row
                    label={t('taxes.filing.row0027')}
                    value={
                        intereses.received?.amount_base == null
                            ? t('taxes.filing.row0027NoData')
                            : money(intereses.received.amount_base, f, t)
                    }
                />
                {Number(intereses.margin_interest_paid?.amount_base ?? 0) > 0 && (
                    <Row
                        label={t('taxes.filing.marginInterest')}
                        value={`${money(intereses.margin_interest_paid?.amount_base, f, t)} · ${t('taxes.filing.marginInterestNote')}`}
                    />
                )}
                <Row label={t('taxes.filing.row0597')} value={
                    (dt.spanish_withholding_base as DataRecord | undefined)?.amount == null
                        ? t('taxes.filing.row0597NoData')
                        : money((dt.spanish_withholding_base as DataRecord | undefined)?.amount, f, t)
                } />
                <Row
                    label={t('taxes.filing.row0588')}
                    value={
                        dt.status === 'pendiente_tme'
                            ? t('taxes.filing.row0588Pending')
                            : money(dt.total_deduction_base, f, t)
                    }
                />
                {lc && Object.keys(lc).length > 0 && (
                    <Row
                        label={t('taxes.filing.lossComp')}
                        value={
                            lc.estimativo === true
                                ? t('taxes.filing.lossCompEstimative', { amount: money(lc.remaining_to_carry_base, f, t) })
                                : t('taxes.filing.lossCompApplied', { gains: money(lc.applied_to_gains_total_base, f, t), income: money(lc.applied_to_income_total_base, f, t) })
                        }
                    />
                )}
            </div>
            <DoubleTaxationByCountry countries={Array.isArray(dt.countries) ? dt.countries as DataRecord[] : []} />
            {dt.partial === true && <p className="mt-2 text-xs text-amber-300">{t('taxes.filing.partialNote')}</p>}
            {typeof filing.tme_percent_manual === 'number' && <Row label={t('taxes.filing.tmeManual')} value={String(filing.tme_percent_manual)} />}
            <TmePreviewForm key={filingSectionKey('tme-preview', year)} year={year} onPreview={onPreview} onReset={onReset} />
            <SaleCasillas key={filingSectionKey('sale-casillas', year)} rows={Array.isArray(acciones.rows) ? acciones.rows as DataRecord[] : []} />
            <WarningList items={warnings} />
        </Section>
    );
}

function SaleCasillas({ rows }: { rows: DataRecord[] }) {
    const t = useT();
    const f = useFormat();
    const [page, setPage] = useState(0);
    const pages = Math.max(1, Math.ceil(rows.length / 10));
    const current = Math.min(page, pages - 1);
    return <div className="mt-4 space-y-2">
        <RecordList key={current} title={t('taxes.filing.saleCasillasTitle')} records={rows.slice(current * 10, (current + 1) * 10)}
            fetchRecords={async () => rows.slice(current * 10, (current + 1) * 10)}
            columns={['ticker', 'date', 'transmission_base', 'acquisition_base', 'gain_base']}
            columnLabels={{ ticker: t('taxes.filing.colValor'), date: t('taxes.filing.colFecha'), transmission_base: t('taxes.filing.colTransmission'), acquisition_base: t('taxes.filing.colAcquisition'), gain_base: t('taxes.filing.colGain') }}
            formatColumns={{ date: (value) => typeof value === 'string' ? f.formatUserDate(value) : t('common.na'),
                transmission_base: (value) => money(value, f, t), acquisition_base: (value) => money(value, f, t), gain_base: (value) => money(value, f, t) }}
            emptyMessage={t('taxes.filing.emptySales')} />
        {pages > 1 && <nav aria-label={t('taxes.filing.navAria')} className="flex items-center justify-between gap-2">
            <Button type="button" size="sm" variant="outline" disabled={current === 0} onClick={() => setPage(current - 1)}>{t('taxes.filing.prev')}</Button>
            <span className="text-xs text-gray-400">{current + 1} / {pages} · {t('taxes.filing.sales', { n: rows.length })}</span>
            <Button type="button" size="sm" variant="outline" disabled={current + 1 >= pages} onClick={() => setPage(current + 1)}>{t('taxes.filing.next')}</Button>
        </nav>}
    </div>;
}

const CATEGORY_LABEL_KEYS: Record<string, Parameters<TFunction>[0]> = {
    valores: 'taxes.modelo720.categoryValores',
    cuentas: 'taxes.modelo720.categoryCuentas',
    inmuebles: 'taxes.modelo720.categoryInmuebles',
};

export function Modelo720Section({ thresholds, file720, unavailable }: {
    thresholds: DataRecord | null;
    file720: DataRecord | null;
    unavailable?: boolean;
}) {
    const t = useT();
    const f = useFormat();
    if (!thresholds) {
        if (!unavailable) return null;
        return (
            <Section
                title={t('taxes.modelo720.title')}
                description={t('taxes.modelo720.descCheck')}
                icon={<Landmark className="h-5 w-5 text-teal-400" />}
            >
                <p className="text-sm text-amber-200/80">
                    {t('taxes.modelo720.unavailable')}
                </p>
            </Section>
        );
    }
    const categories = (thresholds.categories ?? {}) as DataRecord;
    const missingIsin = ((categories.valores as DataRecord | undefined)?.missing_isin ?? []) as string[];
    const foreignUnverified = (thresholds.foreign_unverified ?? []) as DataRecord[];
    const shortPositions = (thresholds.short_positions ?? []) as DataRecord[];
    const unvalued = (thresholds.unvalued ?? []) as DataRecord[];
    const zeroBalance = (thresholds.zero_balance_accounts ?? []) as DataRecord[];
    // El generador devuelve el contenido del fichero junto al recuento de
    // registros: la descarga es del contenido real, no de una reconstrucción.
    const content720 =
        typeof file720?.content === 'string' && file720.content.length > 0 ? file720.content : null;
    const fiscalYear = thresholds.fiscal_year;
    const file720Name = `modelo720-${typeof fiscalYear === 'number' ? String(fiscalYear) : 'ejercicio'}.720`;
    const warnings: string[] = [
        ...(missingIsin.length > 0 ? [t('taxes.modelo720.missingIsin', { tickers: missingIsin.join(', ') })] : []),
        ...foreignUnverified.map((item) => `${humanizeTaxText(String(item.ticker ?? ''))}: ${humanizeTaxText(String(item.reason ?? ''))}`),
        ...shortPositions.map((item) => `${humanizeTaxText(String(item.ticker ?? ''))}: ${t('taxes.modelo720.shortPosition')}`),
        ...unvalued.map((item) => `${humanizeTaxText(String(item.ticker ?? ''))}: ${humanizeTaxText(String(item.reason ?? ''))}`),
        // A17: una cuenta a 0 a 31/12 que no entra en el total se nombra con su motivo.
        ...zeroBalance.map((item) => `${String(item.account ?? item.ticker ?? '')}: ${humanizeTaxText(String(item.reason ?? ''))}`),
    ];
    return (
        <Section
            title={t('taxes.modelo720.title')}
            description={t('taxes.modelo720.descCheckFull')}
            icon={<Landmark className="h-5 w-5 text-teal-400" />}
        >
            <div className="grid gap-1">
                {(['valores', 'cuentas', 'inmuebles'] as const).map((key) => {
                    const category = categories[key] as DataRecord | undefined;
                    if (!category) return null;
                    return (
                        <div key={key} className="border-b border-gray-800/60 py-2 text-sm last:border-0">
                            <div className="flex flex-wrap items-center justify-between gap-2">
                                <span className="text-gray-400">{t(CATEGORY_LABEL_KEYS[key])}</span>
                                <span className="flex items-center gap-3">
                                    <span className="text-gray-200">{(category.status === 'desconocido' || category.status === 'no_evaluable') && !Number(category.total_base) ? t('common.na') : money(category.total_base, f, t)}</span>
                                    <Chip status={String(category.status ?? 'desconocido')} />
                                </span>
                            </div>
                            {Array.isArray(category.reasons) && (category.reasons as string[]).length > 0 && (
                                <ul className="mt-1 space-y-0.5 text-xs leading-5 text-gray-500">
                                    {(category.reasons as string[]).map((reason) => (
                                        <li key={reason}>{humanizeTaxText(reason)}</li>
                                    ))}
                                </ul>
                            )}
                        </div>
                    );
                })}
            </div>
            {file720 && (
                <div className="mt-4 border-t border-gray-800 pt-4">
                    {file720.available === true ? (
                        <div className="space-y-3">
                            <p className="text-sm text-gray-400">
                                {t('taxes.modelo720.fileNote', {
                                    records: typeof file720.detail_records === 'number'
                                        ? f.formatCount(file720.detail_records, t('taxes.modelo720.recordUnit'), t('taxes.modelo720.recordUnitPlural'))
                                        : t('taxes.modelo720.recordsFallback', { n: String(file720.detail_records) }),
                                    length: typeof file720.record_length === 'number' ? t('taxes.modelo720.fileNoteLength', { n: String(file720.record_length) }) : '',
                                    encoding: typeof file720.encoding === 'string' ? t('taxes.modelo720.fileNoteEncoding', { encoding: file720.encoding }) : '',
                                })}
                            </p>
                            {content720 ? (
                                <Button
                                    size="sm"
                                    variant="outline"
                                    onClick={() => downloadFile720(content720, file720Name)}
                                    className="gap-2 border-teal-800 text-teal-300 hover:border-teal-600"
                                >
                                    <FileDown className="h-4 w-4" />
                                    {t('taxes.modelo720.download')}
                                </Button>
                            ) : (
                                <p className="text-sm text-amber-200/80">
                                    {t('taxes.modelo720.noContent', { count: String(file720.detail_records) })}
                                </p>
                            )}
                            {Array.isArray(file720.notas) && (file720.notas as string[]).length > 0 && (
                                <div>
                                    <p className="text-xs font-semibold uppercase text-gray-500">{t('taxes.modelo720.reviewTitle')}</p>
                                    <ul className="mt-1 space-y-1 text-xs leading-5 text-gray-400">
                                        {(file720.notas as string[]).map((nota, i) => (
                                            <li key={`nota-${i}`}>{humanizeTaxText(nota)}</li>
                                        ))}
                                    </ul>
                                </div>
                            )}
                            {Array.isArray(file720.excluded) && (file720.excluded as DataRecord[]).length > 0 && (
                                <div>
                                    <p className="text-xs font-semibold uppercase text-gray-500">{t('taxes.modelo720.excludedTitle')}</p>
                                    <ul className="mt-1 space-y-1 text-xs leading-5 text-amber-200/80">
                                        {(file720.excluded as DataRecord[]).map((item, i) => (
                                            <li key={`${String(item.ticker ?? 'item')}-${i}`}>
                                                {humanizeTaxText(String(item.ticker ?? ''))}: {humanizeTaxText(String(item.reason ?? ''))}
                                            </li>
                                        ))}
                                    </ul>
                                </div>
                            )}
                            {Array.isArray(file720.manual_review) && (file720.manual_review as DataRecord[]).length > 0 && (
                                <div>
                                    <p className="text-xs font-semibold uppercase text-gray-500">{t('taxes.modelo720.manualReviewTitle')}</p>
                                    <ul className="mt-1 space-y-1 text-xs leading-5 text-amber-200/80">
                                        {(file720.manual_review as DataRecord[]).map((item, i) => (
                                            <li key={`${String(item.ticker ?? 'item')}-${i}`}>
                                                {humanizeTaxText(String(item.ticker ?? ''))}: {humanizeTaxText(String(item.reason ?? ''))}
                                            </li>
                                        ))}
                                    </ul>
                                </div>
                            )}
                        </div>
                    ) : (
                        <p className="text-sm text-gray-400">
                            {typeof file720.reason === 'string' && file720.reason
                                ? humanizeTaxText(file720.reason)
                                : t('taxes.modelo720.noFileReason')}
                            {' '}
                            <Link className="inline-flex min-h-[44px] items-center text-teal-300 underline underline-offset-2 sm:min-h-0" href="/settings">
                                {t('taxes.modelo720.completeData')}
                            </Link>
                        </p>
                    )}
                </div>
            )}
            <WarningList items={warnings} />
        </Section>
    );
}
