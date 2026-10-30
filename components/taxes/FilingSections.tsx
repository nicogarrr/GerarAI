'use client';

import Link from 'next/link';
import { useState } from 'react';
import { RecordList } from '@/components/data/RecordViews';
import TmePreviewForm from '@/components/taxes/TmePreviewForm';
import { formatUserDate, formatCountEs } from '@/lib/format';
import { Landmark, FileDown, AlertTriangle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { formatMoney, NA } from '@/lib/format';
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

const CATEGORY_LABELS: Record<string, string> = {
    valores: 'Valores en el extranjero',
    cuentas: 'Cuentas en el extranjero',
    inmuebles: 'Inmuebles en el extranjero',
};

const STATUS_CHIP: Record<string, { label: string; className: string }> = {
    supera: { label: 'Supera el umbral de 50.000 €', className: 'border-amber-700 text-amber-300' },
    por_debajo: { label: 'Por debajo del umbral', className: 'border-teal-800 text-teal-300' },
    desconocido: { label: 'No concluyente (faltan datos)', className: 'border-gray-600 text-gray-300' },
    no_evaluable: { label: 'No evaluable con datos de bróker', className: 'border-gray-700 text-gray-500' },
};

function money(value: unknown): string {
    if (value === null || value === undefined) return NA;
    return formatMoney(value as number | string, 'EUR');
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

function Chip({ status }: { status: string }) {
    const chip = STATUS_CHIP[status] ?? STATUS_CHIP.desconocido;
    return (
        <span className={`inline-block rounded-full border px-2 py-0.5 text-xs ${chip.className}`}>
            {chip.label}
        </span>
    );
}

function percent(value: unknown): string {
    return typeof value === 'number' && Number.isFinite(value)
        ? `${(value * 100).toLocaleString('es-ES', { maximumFractionDigits: 2 })} %`
        : NA;
}

/**
 * Desglose de la casilla 0588 por país (A15, criterio de Hacienda): para
 * cada país, el menor entre la retención con tope del convenio y el TME del
 * ahorro aplicado al dividendo ÍNTEGRO. Sin TME no se inventa el límite.
 */
function DoubleTaxationByCountry({ countries }: { countries: DataRecord[] }) {
    if (countries.length === 0) return null;
    return (
        <div className="mt-3 space-y-1 text-xs leading-5 text-gray-400">
            <p>
                Límite de la deducción (art. 80 LIRPF, como lo aplica Hacienda): por país, el menor entre la retención
                soportada con el tope del convenio y el TME del ahorro aplicado al dividendo íntegro (bruto).
            </p>
            <ul aria-label="Deducción 0588 por país" className="space-y-1">
                {countries.map((c) => {
                    const tmeLimit = c.tme_limit_base == null
                        ? 'falta el TME'
                        : money(c.tme_limit_base);
                    const applied = c.limit_applied === 'bruto_x_tme'
                        ? ' (manda bruto × TME)'
                        : c.limit_applied === 'tope_convenio' ? ' (manda el tope del convenio)' : '';
                    return (
                        <li key={String(c.country)}>
                            {String(c.country)}: bruto {money(c.gross_base)} · retenido {money(c.withheld_base)} · tope
                            convenio ({percent(c.treaty_rate)}) {money(c.treaty_cap_base)} · bruto × TME {tmeLimit} ·
                            deducción {c.deduction_base == null ? NA : money(c.deduction_base)}{applied}
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
    if (!filing) return (
        <Section title="Declaración (Modelo 100)" description="Ayuda de cálculo del IRPF."
            icon={<Landmark className="h-5 w-5 text-teal-400" />}>
            <p className="text-sm text-gray-400">N/D: genera el informe fiscal para consultar las casillas.</p>
        </Section>
    );
    if (filing.available === false) {
        return (
            <Section
                title="Declaración (Modelo 100)"
                description="Casillas orientativas del IRPF calculadas desde tu cartera."
                icon={<Landmark className="h-5 w-5 text-teal-400" />}
            >
                {/* El backend explica el bloqueo (hoy: la cartera no usa EUR
                    como divisa base). El texto de reserva NO dice «no
                    disponible»: dice qué se necesita para que se pueda calcular. */}
                <p className="text-sm text-gray-400">
                    {typeof filing.reason === 'string' && filing.reason
                        ? humanizeTaxText(filing.reason)
                        : 'GerarAI no ha calculado las casillas del Modelo 100 para esta cartera y el motor no ha devuelto el motivo del bloqueo. Las casillas son importes en euros: hace falta que la cartera use EUR como divisa base y que el ejercicio tenga su mapeo verificado contra la orden ministerial vigente.'}
                </p>
            </Section>
        );
    }
    const casillas = (filing.casillas ?? {}) as DataRecord;
    if (casillas.available === false) {
        return (
            <Section
                title="Declaración (Modelo 100)"
                description="Casillas orientativas del IRPF calculadas desde tu cartera."
                icon={<Landmark className="h-5 w-5 text-teal-400" />}
            >
                <p className="text-sm text-gray-400">
                    {typeof casillas.unavailable_reason === 'string' && casillas.unavailable_reason
                        ? humanizeTaxText(casillas.unavailable_reason)
                        : 'Las casillas solo se publican para ejercicios cuyo mapeo está verificado contra la orden ministerial de ese año. Para el resto no se muestran números: haría falta verificar ese mapeo antes de darlos por buenos.'}
                </p>
            </Section>
        );
    }
    if (filing.available !== true || casillas.available !== true) return (
        <Section title="Declaración (Modelo 100)" description="Ayuda de cálculo del IRPF."
            icon={<Landmark className="h-5 w-5 text-teal-400" />}>
            <p className="text-sm text-gray-400">N/D: el motor no ha confirmado el mapeo de este ejercicio.</p>
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
            ? [`Pagos especiales fuera de los dividendos ordinarios (revisión manual): ${specialTickers.join(', ')}`]
            : []),
    ];
    return (
        <Section
            title="Declaración (Modelo 100)"
            description="Casillas orientativas del IRPF calculadas desde tu cartera. Ayuda de cómputo: no apto para declarar sin la validación de un asesor fiscal."
            icon={<Landmark className="h-5 w-5 text-teal-400" />}
        >
            <div className="grid gap-1">
                <Row label="0328 · Transmisión global" value={money(acciones['0328_transmision_global'])} />
                <Row label="0331 · Adquisición global" value={money(acciones['0331_adquisicion_global'])} />
                <Row label="0339 · Suma de ganancias" value={money(acciones['0339_suma_ganancias'])} />
                <Row label="0340 · Suma de pérdidas" value={money(acciones['0340_suma_perdidas'])} />
                <Row label="0029 · Dividendos íntegros" value={money(dividendos['0029_ingresos_integros'])} />
                <Row
                    label="0027 · Intereses cobrados (cuenta del bróker)"
                    value={
                        intereses.received?.amount_base == null
                            ? 'Sin datos: hay intereses sin tipo de cambio de su fecha (revisión manual)'
                            : money(intereses.received.amount_base)
                    }
                />
                {Number(intereses.margin_interest_paid?.amount_base ?? 0) > 0 && (
                    <Row
                        label="Intereses de margen pagados (no deducibles)"
                        value={`${money(intereses.margin_interest_paid?.amount_base)} · no se restan en la declaración`}
                    />
                )}
                <Row label="0597 · Retenciones españolas" value={
                    (dt.spanish_withholding_base as DataRecord | undefined)?.amount == null
                        ? 'Sin datos: retenciones españolas incompletas'
                        : money((dt.spanish_withholding_base as DataRecord | undefined)?.amount)
                } />
                <Row
                    label="0588 · Deducción por doble imposición"
                    value={
                        dt.status === 'pendiente_tme'
                            ? 'Falta el tipo medio efectivo: introduce el TME de la base liquidable del ahorro de tu borrador para calcular la deducción'
                            : money(dt.total_deduction_base)
                    }
                />
                {lc && Object.keys(lc).length > 0 && (
                    <Row
                        label="Compensación de pérdidas de años anteriores"
                        value={
                            lc.estimativo === true
                                ? `Estimativa (no trasladable a casillas): restan ${money(lc.remaining_to_carry_base)} por arrastrar`
                                : `Aplicada: ${money(lc.applied_to_gains_total_base)} a ganancias y ${money(lc.applied_to_income_total_base)} a rendimientos`
                        }
                    />
                )}
            </div>
            <DoubleTaxationByCountry countries={Array.isArray(dt.countries) ? dt.countries as DataRecord[] : []} />
            {dt.partial === true && <p className="mt-2 text-xs text-amber-300">N/D en la deducción total: hay pagos que requieren revisión manual.</p>}
            {typeof filing.tme_percent_manual === 'number' && <Row label="TME manual aplicado (%)" value={String(filing.tme_percent_manual)} />}
            <TmePreviewForm key={filingSectionKey('tme-preview', year)} year={year} onPreview={onPreview} onReset={onReset} />
            <SaleCasillas key={filingSectionKey('sale-casillas', year)} rows={Array.isArray(acciones.rows) ? acciones.rows as DataRecord[] : []} />
            <WarningList items={warnings} />
        </Section>
    );
}

function SaleCasillas({ rows }: { rows: DataRecord[] }) {
    const [page, setPage] = useState(0);
    const pages = Math.max(1, Math.ceil(rows.length / 10));
    const current = Math.min(page, pages - 1);
    return <div className="mt-4 space-y-2">
        <RecordList key={current} title="Casillas por venta" records={rows.slice(current * 10, (current + 1) * 10)}
            fetchRecords={async () => rows.slice(current * 10, (current + 1) * 10)}
            columns={['ticker', 'date', 'transmission_base', 'acquisition_base', 'gain_base']}
            columnLabels={{ ticker: 'Valor', date: 'Fecha', transmission_base: 'Transmisión (€)', acquisition_base: 'Adquisición (€)', gain_base: 'Resultado computable (€)' }}
            formatColumns={{ date: (value) => typeof value === 'string' ? formatUserDate(value) : NA,
                transmission_base: money, acquisition_base: money, gain_base: money }}
            emptyMessage="No hay ventas con casillas para este ejercicio." />
        {pages > 1 && <nav aria-label="Páginas de casillas por venta" className="flex items-center justify-between gap-2">
            <Button type="button" size="sm" variant="outline" disabled={current === 0} onClick={() => setPage(current - 1)}>Anterior</Button>
            <span className="text-xs text-gray-400">{current + 1} / {pages} · {rows.length} ventas</span>
            <Button type="button" size="sm" variant="outline" disabled={current + 1 >= pages} onClick={() => setPage(current + 1)}>Siguiente</Button>
        </nav>}
    </div>;
}

export function Modelo720Section({ thresholds, file720, unavailable }: {
    thresholds: DataRecord | null;
    file720: DataRecord | null;
    unavailable?: boolean;
}) {
    if (!thresholds) {
        if (!unavailable) return null;
        return (
            <Section
                title="Modelo 720 (bienes en el extranjero)"
                description="Chequeo orientativo del umbral de 50.000 € por categoría."
                icon={<Landmark className="h-5 w-5 text-teal-400" />}
            >
                <p className="text-sm text-amber-200/80">
                    El chequeo 720 no está disponible ahora mismo (error del motor). No significa que no te aplique: inténtalo de nuevo más tarde.
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
        ...(missingIsin.length > 0 ? [`Sin ISIN (necesario para declarar el valor): ${missingIsin.join(', ')}`] : []),
        ...foreignUnverified.map((item) => `${humanizeTaxText(String(item.ticker ?? ''))}: ${humanizeTaxText(String(item.reason ?? ''))}`),
        ...shortPositions.map((item) => `${humanizeTaxText(String(item.ticker ?? ''))}: posición corta, no cuenta como bien en el 720`),
        ...unvalued.map((item) => `${humanizeTaxText(String(item.ticker ?? ''))}: ${humanizeTaxText(String(item.reason ?? ''))}`),
        // A17: una cuenta a 0 a 31/12 que no entra en el total se nombra con su motivo.
        ...zeroBalance.map((item) => `${String(item.account ?? item.ticker ?? '')}: ${humanizeTaxText(String(item.reason ?? ''))}`),
    ];
    return (
        <Section
            title="Modelo 720 (bienes en el extranjero)"
            description="Chequeo orientativo del umbral de 50.000 € por categoría. Un «no concluyente» no es un «no»: falta algún dato para afirmarlo."
            icon={<Landmark className="h-5 w-5 text-teal-400" />}
        >
            <div className="grid gap-1">
                {(['valores', 'cuentas', 'inmuebles'] as const).map((key) => {
                    const category = categories[key] as DataRecord | undefined;
                    if (!category) return null;
                    return (
                        <div key={key} className="border-b border-gray-800/60 py-2 text-sm last:border-0">
                            <div className="flex flex-wrap items-center justify-between gap-2">
                                <span className="text-gray-400">{CATEGORY_LABELS[key]}</span>
                                <span className="flex items-center gap-3">
                                    <span className="text-gray-200">{(category.status === 'desconocido' || category.status === 'no_evaluable') && !Number(category.total_base) ? NA : money(category.total_base)}</span>
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
                                Borrador de fichero generado ({typeof file720.detail_records === 'number' ? formatCountEs(file720.detail_records, 'registro de detalle', 'registros de detalle') : `${String(file720.detail_records)} registros de detalle`}
                                {typeof file720.record_length === 'number' ? ` de ${String(file720.record_length)} bytes` : ''}
                                {typeof file720.encoding === 'string' ? `, en ${file720.encoding}` : ''}). Es el
                                contenido real que produce el generador, no una estimación: puedes descargarlo y
                                revisarlo, pero es una ayuda de cómputo y no un fichero oficial listo para
                                presentar.
                            </p>
                            {content720 ? (
                                <Button
                                    size="sm"
                                    variant="outline"
                                    onClick={() => downloadFile720(content720, file720Name)}
                                    className="gap-2 border-teal-800 text-teal-300 hover:border-teal-600"
                                >
                                    <FileDown className="h-4 w-4" />
                                    Descargar borrador del 720
                                </Button>
                            ) : (
                                <p className="text-sm text-amber-200/80">
                                    El generador informa del número de registros ({String(file720.detail_records)}) pero
                                    no su contenido, así que no hay nada que descargar: es una lectura fallida, no
                                    un fichero esperando permiso. Vuelve a cargar la página; si el contador
                                    aparece sin contenido otra vez, no hay forma de obtenerlo desde aquí.
                                </p>
                            )}
                            {Array.isArray(file720.notas) && (file720.notas as string[]).length > 0 && (
                                <div>
                                    <p className="text-xs font-semibold uppercase text-gray-500">Lo que hay que revisar antes de usarlo</p>
                                    <ul className="mt-1 space-y-1 text-xs leading-5 text-gray-400">
                                        {(file720.notas as string[]).map((nota, i) => (
                                            <li key={`nota-${i}`}>{humanizeTaxText(nota)}</li>
                                        ))}
                                    </ul>
                                </div>
                            )}
                            {Array.isArray(file720.excluded) && (file720.excluded as DataRecord[]).length > 0 && (
                                <div>
                                    <p className="text-xs font-semibold uppercase text-gray-500">Registros excluidos del fichero</p>
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
                                    <p className="text-xs font-semibold uppercase text-gray-500">Revisión manual necesaria</p>
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
                                : 'El generador no ha producido fichero y no ha devuelto el motivo del bloqueo; revisa los registros excluidos y la revisión manual de arriba para saber qué falta.'}
                            {' '}
                            <Link className="inline-flex min-h-[44px] items-center text-teal-300 underline underline-offset-2 sm:min-h-0" href="/settings">
                                Completar datos fiscales
                            </Link>
                        </p>
                    )}
                </div>
            )}
            <WarningList items={warnings} />
        </Section>
    );
}
