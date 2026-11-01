'use client';

import { useState, type ReactNode } from 'react';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Inbox, Loader2, RefreshCw } from 'lucide-react';
import { showErrorToast } from '@/lib/toast';
import { useT } from '@/lib/i18n/client';
import type { TranslateFn } from '@/lib/i18n/translate';
import { Pager } from '@/components/research/Pager';

export type DataRecord = Record<string, unknown>;

/** Máximos de legibilidad para un valor compuesto dentro de una celda. */
const MAX_VALUE_ITEMS = 6;
const MAX_VALUE_CHARS = 400;

/** `target_pct` -> `target pct`: la clave interna no se muestra como snake_case. */
function humanizeKey(key: string): string {
    return key.replaceAll('_', ' ').trim();
}

/**
 * Resumen legible de un array u objeto.
 *
 * Antes caía en `JSON.stringify` y se volcaba dentro de una celda con
 * `line-clamp`: un bloque de código truncado, con claves internas en crudo y
 * sin nada que se pudiera leer. Ahora se declara como lista de
 * «clave: valor», y lo que no cabe se cuenta («+N más») en vez de desaparecer
 * sin aviso. La profundidad está acotada: un anidamiento más profundo que
 * `depth` se marca como tal, no se serializa.
 */
/** «+N más» / «+N more»: sin traductor (llamadas antiguas) se mantiene el español. */
function moreItems(count: number, t?: TranslateFn): string {
    return t ? t('data.moreItems', { count }) : `+${count} más`;
}

function describeValue(value: unknown, depth: number, t?: TranslateFn): string {
    if (value === null || value === undefined) return '—';
    if (typeof value === 'boolean') return value ? (t ? t('data.yes') : 'Sí') : (t ? t('data.no') : 'No');
    if (typeof value === 'number') return String(value);
    if (typeof value === 'string') return value;
    if (value instanceof Date) return value.toISOString();
    if (depth <= 0) return Array.isArray(value) ? `[${value.length}]` : '{…}';
    if (Array.isArray(value)) {
        if (value.length === 0) return '—';
        const shown = value.slice(0, MAX_VALUE_ITEMS).map((item) => describeValue(item, depth - 1, t));
        const rest = value.length - shown.length;
        return `${shown.join(' · ')}${rest > 0 ? ` · ${moreItems(rest, t)}` : ''}`;
    }
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) return '—';
    const shown = entries
        .slice(0, MAX_VALUE_ITEMS)
        .map(([key, item]) => `${humanizeKey(key)}: ${describeValue(item, depth - 1, t)}`);
    const rest = entries.length - shown.length;
    return `${shown.join(' · ')}${rest > 0 ? ` · ${moreItems(rest, t)}` : ''}`;
}

/** Convierte cualquier valor a texto plano legible en tabla/cards */
export function formatRecordValue(value: unknown, t?: TranslateFn): string {
    if (value === null || value === undefined) return '—';
    if (typeof value === 'boolean') return value ? (t ? t('data.yes') : 'Sí') : (t ? t('data.no') : 'No');
    if (typeof value === 'object') {
        const text = describeValue(value, 2, t);
        return text.length > MAX_VALUE_CHARS ? `${text.slice(0, MAX_VALUE_CHARS - 1)}…` : text;
    }
    return String(value);
}

/** Normaliza un array de respuestas a DataRecord[] (los primitivos se envuelven) */
export function toRecords(data: unknown[]): DataRecord[] {
    return data.map((item) => (
        item !== null && typeof item === 'object' && !Array.isArray(item)
            ? item as DataRecord
            : { value: item }
    ));
}

/**
 * Nº máximo de columnas de la tabla. El ancho lo resuelve CSS: por debajo de
 * `md` la tabla no se muestra y solo se ven las cards, así que medir el viewport
 * en JS solo añadiría un reflow después de hidratar. El tope protege el caso de
 * `md` con 6 columnas + "Acciones", que es lo que hace scrollear el contenedor.
 */
const COLUMNS_WIDE = 6;

/**
 * Selecciona columnas legibles: claves planas (sin objetos anidados), con
 * preferencia explícita. `max` acota solo las columnas *inferidas* — si quien
 * llama pasa `preferred`, esas son las que quiere ver y no se recortan.
 */
export function pickColumns(records: DataRecord[], preferred?: string[], max: number = COLUMNS_WIDE): string[] {
    if (preferred && preferred.length > 0) return preferred;
    const keys: string[] = [];
    const limit = Math.max(1, max);
    for (const record of records.slice(0, 3)) {
        for (const key of Object.keys(record)) {
            if (keys.includes(key)) continue;
            const value = record[key];
            if (value !== null && typeof value === 'object') continue;
            keys.push(key);
        }
        if (keys.length >= limit) break;
    }
    return keys;
}

/** Construye el href a /research/[ticker] desde la clave `ticker` del registro (o null si no hay) */
export function researchHrefFor(record: DataRecord, key = 'ticker'): string | null {
    const value = record[key];
    if (typeof value !== 'string' || !value.trim()) return null;
    return `/research/${encodeURIComponent(value.trim().toUpperCase())}`;
}

/**
 * Sustituye campos de una fila ya pintada. Se entrega a `rowActions` para que
 * una mutación (Aplicar, archivar...) se refleje en la fila sin esperar a un
 * refresco manual: el parche debe traer la respuesta del backend, nunca un
 * estado local inventado.
 */
export type ReplaceRecord = (patch: DataRecord) => void;

export interface RecordListProps {
    title: string;
    /**
     * Nivel del título de la tarjeta. Por defecto h3 (tarjeta dentro de una
     * sección); una pantalla que la pinta justo bajo su h1 pasa "h2" para no
     * saltarse un nivel (axe heading-order, visto en /taxes con Lighthouse).
     */
    titleAs?: 'h2' | 'h3';
    description?: string;
    icon?: ReactNode;
    /** Oculta título, descripción e icono (la página ya los muestra): queda solo «Refrescar». El título sigue como texto accesible. */
    hideTitle?: boolean;
    /** Datos iniciales recibidos desde el servidor */
    records: DataRecord[];
    /** Server action que devuelve el listado (para refresco client-side) */
    fetchRecords: () => Promise<unknown[]>;
    /** Columnas explícitas; si se omite se infieren de los datos */
    columns?: string[];
    emptyMessage?: string;
    /** CTA del estado vacío (primer paso: crear, importar, ir a...) */
    emptyAction?: ReactNode;
    /**
     * Acciones por fila (botón Aplicar, eliminar, etc.). El tercer argumento
     * sustituye campos de esa fila en el estado del listado, para que la acción
     * se vea aplicada sin un refresco manual.
     */
    rowActions?: (record: DataRecord, index: number, replace: ReplaceRecord) => ReactNode;
    /** Columnas cuyo valor se renderiza como enlace (p.ej. ticker -> /research/[ticker]) */
    linkColumns?: Record<string, (record: DataRecord, index: number) => string | null | undefined>;
    /** Formateadores por columna (p. ej. importes con la divisa de la fila). */
    formatColumns?: Record<string, (value: unknown, record: DataRecord) => string>;
    /** Etiquetas de cabecera por columna; las no mapeadas muestran la clave cruda (nunca se ocultan) */
    columnLabels?: Record<string, string>;
    footer?: ReactNode;
    /**
     * Filas por página. Sin esta prop la lista se pinta entera (una sola
     * página): con cientos de filas el scroll móvil era interminable. Con
     * paginador arriba y abajo, como manda la regla de listas largas.
     */
    pageSize?: number;
    /** Etiqueta singular del paginador («registros» por defecto). */
    paginationLabel?: string;
}

export function RecordList({
    title,
    titleAs,
    description,
    icon,
    hideTitle = false,
    records: initialRecords,
    fetchRecords,
    columns,
    emptyMessage,
    emptyAction,
    rowActions,
    linkColumns,
    formatColumns,
    columnLabels,
    footer,
    pageSize,
    paginationLabel,
}: RecordListProps) {
    const t = useT();
    const resolvedEmptyMessage = emptyMessage ?? t('data.emptyDefault');
    const resolvedPaginationLabel = paginationLabel ?? t('data.records');
    const [records, setRecords] = useState<DataRecord[]>(initialRecords);
    const [loading, setLoading] = useState(false);

    const refresh = async () => {
        setLoading(true);
        try {
            const data = await fetchRecords();
            setRecords(toRecords(data));
        } catch (error) {
            showErrorToast(error, { onRetry: refresh });
        } finally {
            setLoading(false);
        }
    };

    // La página se acota a las filas visibles; los índices que reciben
    // `rowActions` y `replaceRecord` siguen siendo los de la lista completa,
    // o un «Aplicar» en página 2 parchearía la fila equivocada.
    const [page, setPage] = useState(1);
    const pages = pageSize ? Math.max(1, Math.ceil(records.length / pageSize)) : 1;
    const currentPage = Math.min(page, pages);
    const pageStart = pageSize ? (currentPage - 1) * pageSize : 0;
    const visibleRecords = pageSize ? records.slice(pageStart, pageStart + pageSize) : records;
    const pager = pages > 1 ? (
        <Pager label={resolvedPaginationLabel} onPage={setPage} page={currentPage} pages={pages} total={records.length} />
    ) : null;

    const visibleColumns = pickColumns(records, columns);
    const cellText = (record: DataRecord, column: string) => {
        const format = formatColumns?.[column];
        return format ? format(record[column], record) : formatRecordValue(record[column], t);
    };
    const cellHref = (record: DataRecord, index: number, column: string) =>
        linkColumns?.[column]?.(record, index) ?? null;
    // El parche se aplica sobre la fila por posición: la lista solo cambia
    // aquí (mutación) o en `refresh` (recarga completa), nunca por props.
    const replaceRecord = (index: number): ReplaceRecord => (patch) =>
        setRecords((current) => current.map((row, position) => (position === index ? { ...row, ...patch } : row)));

    return (
        <Card className="rounded-lg border border-gray-700">
            <CardHeader className={`flex flex-col gap-3 border-b border-gray-700/50 pb-4 sm:flex-row sm:items-center sm:justify-between sm:space-y-0${hideTitle ? ' items-end' : ''}`}>
                {hideTitle ? (
                    <CardTitle as={titleAs} className="sr-only">{title}</CardTitle>
                ) : (
                    <div className="flex items-center gap-3">
                        {icon}
                        <div>
                            <CardTitle as={titleAs} className="text-lg font-semibold text-gray-100">{title}</CardTitle>
                            {description && <CardDescription className="mt-0.5 text-sm text-gray-500">{description}</CardDescription>}
                        </div>
                    </div>
                )}
                <Button
                    variant="ghost"
                    size="sm"
                    onClick={refresh}
                    disabled={loading}
                    className="gap-2 text-gray-400 hover:text-teal-400"
                >
                    <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} aria-hidden="true" />
                    {t('data.refresh')}
                </Button>
            </CardHeader>
            <CardContent className="pt-4">
                {loading && records.length === 0 ? (
                    <div className="flex items-center justify-center py-10 text-gray-500">
                        <Loader2 className="mr-2 h-5 w-5 animate-spin" aria-hidden="true" /> {t('common.states.loading')}
                    </div>
                ) : records.length === 0 ? (
                    <EmptyState action={emptyAction} icon={Inbox} title={resolvedEmptyMessage} />
                ) : visibleColumns.length === 0 ? (
                    <div className="space-y-2">
                        {records.map((record, index) => (
                            <pre key={index} className="overflow-x-auto rounded border border-gray-700/50 bg-surface-0/50 p-3 text-xs text-gray-400">
                                {JSON.stringify(record, null, 2)}
                            </pre>
                        ))}
                    </div>
                ) : (
                    <>
                        {pager}
                        {/* Escritorio: tabla completa, con la region de scroll enfocada por teclado */}
                        <div className="hidden overflow-x-auto md:block">
                            <Table regionLabel={title}>
                                <TableCaption className="sr-only">{title}</TableCaption>
                                <TableHeader>
                                    <TableRow className="border-gray-700 hover:bg-transparent">
                                        {visibleColumns.map((column) => (
                                            <TableHead key={column} className="text-xs font-semibold uppercase text-gray-500">
                                                {columnLabels?.[column] ?? column}
                                            </TableHead>
                                        ))}
                                        {rowActions && <TableHead className="text-right text-xs font-semibold uppercase text-gray-500">{t('data.actions')}</TableHead>}
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {visibleRecords.map((record, localIndex) => {
                                        const index = pageStart + localIndex;
                                        return (
                                        <TableRow key={index} className="border-gray-700/50">
                                            {visibleColumns.map((column) => {
                                                const href = cellHref(record, index, column);
                                                return (
                                                    <TableCell key={column} className="text-sm text-gray-300">
                                                        {href ? (
                                                            <Link
                                                                href={href}
                                                                className="font-mono font-semibold text-teal-300 hover:text-teal-200 hover:underline"
                                                            >
                                                                {cellText(record, column)}
                                                            </Link>
                                                        ) : (
                                                            <span className="line-clamp-3">{cellText(record, column)}</span>
                                                        )}
                                                    </TableCell>
                                                );
                                            })}
                                            {rowActions && (
                                                <TableCell className="text-right">
                                                    {rowActions(record, index, replaceRecord(index))}
                                                </TableCell>
                                            )}
                                        </TableRow>
                                        );
                                    })}
                                </TableBody>
                            </Table>
                        </div>
                        {/* Móvil: cards equivalentes, sin scroll horizontal */}
                        <ul className="space-y-3 md:hidden">
                            {visibleRecords.map((record, localIndex) => {
                                const index = pageStart + localIndex;
                                return (
                                <li className="min-w-0 rounded-xl border border-gray-700/50 bg-gray-800/40 p-4" key={index}>
                                    <dl className="grid grid-cols-2 gap-x-3 gap-y-2">
                                        {visibleColumns.map((column) => {
                                            const href = cellHref(record, index, column);
                                            return (
                                                <div className="min-w-0" key={column}>
                                                    <dt className="text-[11px] uppercase tracking-wide text-gray-500">{columnLabels?.[column] ?? column}</dt>
                                                    <dd className="break-words text-sm text-gray-200">
                                                        {href ? (
                                                            <Link
                                                                href={href}
                                                                className="font-mono font-semibold text-teal-300 hover:text-teal-200 hover:underline"
                                                            >
                                                                {cellText(record, column)}
                                                            </Link>
                                                        ) : (
                                                            cellText(record, column)
                                                        )}
                                                    </dd>
                                                </div>
                                            );
                                        })}
                                    </dl>
                                    {rowActions ? (
                                        <div className="mt-3 flex flex-wrap justify-end gap-2 border-t border-gray-700/50 pt-3">
                                            {rowActions(record, index, replaceRecord(index))}
                                        </div>
                                    ) : null}
                                </li>
                                );
                            })}
                        </ul>
                        {pager}
                    </>
                )}
                {footer && <div className="mt-4">{footer}</div>}
            </CardContent>
        </Card>
    );
}

export interface RecordDetailProps {
    title: string;
    /**
     * Nivel del título de la tarjeta. Por defecto h3 (tarjeta dentro de una
     * sección); una pantalla que la pinta justo bajo su h1 pasa "h2" para no
     * saltarse un nivel (axe heading-order, visto en /taxes con Lighthouse).
     */
    titleAs?: 'h2' | 'h3';
    description?: string;
    icon?: ReactNode;
    record: DataRecord | null;
    fetchRecord?: () => Promise<unknown>;
    emptyMessage?: string;
    /** CTA del estado vacío (primer paso: crear, importar, ir a...) */
    emptyAction?: ReactNode;
    /** Contenido adicional (botones de acción sobre el objeto, p.ej. regenerar) */
    actions?: ReactNode;
    /** Máximo de claves a mostrar; por defecto todas */
    maxKeys?: number;
    /** Claves internas/debug que no se muestran (p.ej. trace del backend). */
    hiddenKeys?: string[];
    /**
     * Etiquetas de campo por clave; las no mapeadas muestran la clave cruda
     * (nunca se ocultan), igual que `columnLabels` en RecordList. Sin este mapa
     * la tarjeta pintaba la clave del backend en mayúsculas («PLAN_EXISTS»).
     */
    columnLabels?: Record<string, string>;
    formatColumns?: Record<string, (value: unknown, record: DataRecord) => string>;
}

/** Tarjeta clave/valor para respuestas de objeto único (plan, drift, risk dashboard, reporte fiscal...) */
export function RecordDetail({
    title,
    titleAs,
    description,
    icon,
    record,
    fetchRecord,
    emptyMessage,
    emptyAction,
    actions,
    maxKeys = 24,
    hiddenKeys,
    columnLabels,
    formatColumns,
}: RecordDetailProps) {
    const t = useT();
    const resolvedEmptyMessage = emptyMessage ?? t('data.emptyDefault');
    const [data, setData] = useState<DataRecord | null>(record);

    // F387: router.refresh() entrega un `record` nuevo; sin este sync la tarjeta
    // conserva el estado copiado una sola vez y no refleja el plan guardado.
    // Se ajusta durante el render (estado derivado de props), sin efecto.
    const [syncedRecord, setSyncedRecord] = useState(record);
    if (record !== syncedRecord) {
        setSyncedRecord(record);
        setData(record);
    }

    const refresh = async () => {
        if (!fetchRecord) return;
        try {
            const result = await fetchRecord();
            if (result === null) {
                // null = estado vacío honesto (p.ej. plan sin configurar)
                setData(null);
            } else if (typeof result === 'object' && !Array.isArray(result)) {
                setData(result as DataRecord);
            }
        } catch (error) {
            showErrorToast(error, { onRetry: refresh });
        }
    };

    const hidden = new Set((hiddenKeys ?? []).map((key) => key.toLowerCase()));
    const entries = data
        ? Object.entries(data)
              .filter(([key]) => !hidden.has(key.toLowerCase()))
              .slice(0, maxKeys)
        : [];

    return (
        <Card className="rounded-lg border border-gray-700">
            <CardHeader className="flex flex-col gap-3 border-b border-gray-700/50 pb-4 sm:flex-row sm:items-center sm:justify-between sm:space-y-0">
                <div className="flex items-center gap-3">
                    {icon}
                    <div>
                        <CardTitle as={titleAs} className="text-lg font-semibold text-gray-100">{title}</CardTitle>
                        {description && <CardDescription className="mt-0.5 text-sm text-gray-500">{description}</CardDescription>}
                    </div>
                </div>
                <div className="flex items-center gap-2">
                    {fetchRecord && (
                        <Button
                            variant="ghost"
                            size="sm"
                            onClick={refresh}
                            className="gap-2 text-gray-400 hover:text-teal-400"
                        >
                            <RefreshCw className="h-4 w-4" aria-hidden="true" />
                            {t('data.refresh')}
                        </Button>
                    )}
                    {actions}
                </div>
            </CardHeader>
            <CardContent className="pt-4">
                {!data || entries.length === 0 ? (
                    <EmptyState action={emptyAction} icon={Inbox} title={resolvedEmptyMessage} />
                ) : (
                    <div className="grid grid-cols-1 gap-px overflow-hidden rounded-lg border border-gray-700/50 bg-gray-700/40 sm:grid-cols-2">
                        {entries.map(([key, value]) => (
                            <div key={key} className="flex flex-col gap-1 bg-surface-0/60 p-3">
                                <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">{columnLabels?.[key] ?? key}</span>
                                <span className="break-words text-sm text-gray-200">
                                    <span className={formatColumns?.[key] ? "whitespace-pre-line" : "line-clamp-4"}>{formatColumns?.[key] ? formatColumns[key](value, data!) : formatRecordValue(value, t)}</span>
                                </span>
                            </div>
                        ))}
                    </div>
                )}
            </CardContent>
        </Card>
    );
}
