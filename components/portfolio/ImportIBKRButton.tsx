'use client';

import { useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Loader2, Landmark, Upload } from 'lucide-react';
import { importFromIBKR, importIBKRCsv, importIBKRXml } from '@/lib/actions/portfolio.actions';
import { toast } from 'sonner';
import { useT, useFormat } from '@/lib/i18n/client';
import type { TranslateFn as TFunction } from '@/lib/i18n/translate';
import { createFormatters, type Formatters } from '@/lib/format';
import type { TranslationKey } from '@/lib/i18n/t';
import { t } from '@/lib/i18n/t';

const esT: TFunction = t;
const esF = createFormatters('es');

/** «1 posición» / «2 posiciones» en el locale activo: dos claves por nombre. */
function noun(n: number, one: TranslationKey, many: TranslationKey, ti: TFunction, f: Formatters): string {
    return ti(n === 1 ? one : many, { n: f.formatNumber(n, { maximumFractionDigits: 0 }) });
}
import { showErrorToast } from '@/lib/toast';

interface ImportIBKRButtonProps {
    userId: string;
}

type ImportCounts = {
    status: string;
    rows_skipped?: number | null;
    row_errors?: string[] | null;
    identity_warning?: string | null;
    positions_imported?: unknown;
    trades_imported?: unknown;
    duplicate_trades?: unknown;
    dividends_imported?: unknown;
    fees_imported?: unknown;
    cash_imported?: unknown;
};

function num(value: unknown): number | null {
    return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

export function describeResult(result: ImportCounts, ti: TFunction = esT, f: Formatters = esF): string {
    const parts: string[] = [];
    const positions = num(result.positions_imported);
    if (positions !== null) {
        const trades = num(result.trades_imported) ?? 0;
        const dividends = num(result.dividends_imported) ?? 0;
        const fees = num(result.fees_imported) ?? 0;
        const cash = num(result.cash_imported) ?? 0;
        parts.push(
            ti('portfolio.importIbk.resultFlexPrefix') +
            [
                noun(positions, 'portfolio.importIbk.nounPositionOne', 'portfolio.importIbk.nounPositionMany', ti, f),
                noun(trades, 'portfolio.importIbk.nounTradeOne', 'portfolio.importIbk.nounTradeMany', ti, f),
                noun(dividends, 'portfolio.importIbk.nounDividendOne', 'portfolio.importIbk.nounDividendMany', ti, f),
                noun(fees, 'portfolio.importIbk.nounFeeOne', 'portfolio.importIbk.nounFeeMany', ti, f),
                noun(cash, 'portfolio.importIbk.nounCashOne', 'portfolio.importIbk.nounCashMany', ti, f),
            ].join(', ')
        );
    } else {
        const trades = num(result.trades_imported) ?? 0;
        parts.push(ti('portfolio.importIbk.resultCsvPrefix') + noun(trades, 'portfolio.importIbk.nounImportedTradeOne', 'portfolio.importIbk.nounImportedTradeMany', ti, f));
    }
    const duplicates = num(result.duplicate_trades) ?? 0;
    if (duplicates > 0) {
        parts.push(noun(duplicates, 'portfolio.importIbk.nounDuplicateOne', 'portfolio.importIbk.nounDuplicateMany', ti, f));
    }
    if (result.rows_skipped) {
        parts.push(noun(result.rows_skipped, 'portfolio.importIbk.nounSkippedRowOne', 'portfolio.importIbk.nounSkippedRowMany', ti, f));
    }
    return parts.join(' · ');
}

/**
 * Las subidas viajan como argumento de una server action, cuyo cuerpo está
 * limitado a 4 MB (next.config.ts). Con margen para la serialización, un
 * fichero mayor fallaba con un error genérico tras subirlo entero.
 */
export const MAX_UPLOAD_BYTES = 3.5 * 1024 * 1024;

function megabytes(bytes: number, f: Formatters = esF): string {
    return `${f.formatNumber(bytes / (1024 * 1024), { maximumFractionDigits: 1 })} MB`;
}

/** Motivo para no enviar el fichero, o null si se puede subir. */
export function uploadProblem(file: { size: number }, ti: TFunction = esT, f: Formatters = esF): string | null {
    if (file.size === 0) return ti('portfolio.importIbk.fileEmpty');
    if (file.size > MAX_UPLOAD_BYTES) {
        return ti('portfolio.importIbk.fileTooBig', { size: megabytes(file.size, f), max: megabytes(MAX_UPLOAD_BYTES, f) });
    }
    return null;
}

const ROW_ERRORS_SHOWN = 5;

/** Detalle de las filas con avisos: hasta 5, y cuántas quedan. */
export function rowErrorDetail(errors: string[], ti: TFunction = esT, f: Formatters = esF): string {
    const shown = errors.slice(0, ROW_ERRORS_SHOWN).join('\n');
    const rest = errors.length - ROW_ERRORS_SHOWN;
    return rest > 0 ? `${shown}\n${noun(rest, 'portfolio.importIbk.nounMoreNoticeOne', 'portfolio.importIbk.nounMoreNoticeMany', ti, f)}` : shown;
}

type ImportOutcome = ImportCounts & { message?: string | null };

/**
 * Avisos del resultado de una importación (Flex o fichero), los mismos en las
 * dos vías. Antes la vía Flex enseñaba solo 3 avisos sin decir cuántos había y
 * el fallo sin motivo salía como «Importación falló: rejected».
 * Devuelve true si se importó.
 */
export function notifyImportResult(result: ImportOutcome, ti: TFunction = esT, f: Formatters = esF): boolean {
    if (result.status !== 'imported') {
        toast.error(result.message || ti('portfolio.importIbk.importFailed'), { duration: 10000 });
        return false;
    }
    toast.success(describeResult(result, ti, f));
    if (result.identity_warning) toast.warning(result.identity_warning);
    if (result.row_errors?.length) {
        toast.warning(
            ti('portfolio.importIbk.rowWarnings', {
                rows: noun(result.row_errors.length, 'portfolio.importIbk.nounWarnRowOne', 'portfolio.importIbk.nounWarnRowMany', ti, f),
                first: result.row_errors[0],
            }),
            { duration: 12000, description: rowErrorDetail(result.row_errors, ti, f) }
        );
    }
    return true;
}

export default function ImportIBKRButton({ userId }: ImportIBKRButtonProps) {
    const ti = useT();
    const f = useFormat();
    const [isImporting, setIsImporting] = useState(false);
    const [isUploading, setIsUploading] = useState(false);
    const fileInputRef = useRef<HTMLInputElement>(null);
    const router = useRouter();

    async function handleImport() {
        try {
            setIsImporting(true);
            const result = await importFromIBKR(userId);
            if (!notifyImportResult(result, ti, f)) return;
            router.refresh();
        } catch (error) {
            showErrorToast(error);
        } finally {
            // Small delay to allow the page to refresh
            setTimeout(() => setIsImporting(false), 1000);
        }
    }

    async function handleFile(event: React.ChangeEvent<HTMLInputElement>) {
        const file = event.target.files?.[0];
        event.target.value = '';
        if (!file) return;
        const problem = uploadProblem(file, ti, f);
        if (problem) {
            toast.error(problem, { duration: 10000 });
            return;
        }
        const isCsv = file.name.toLowerCase().endsWith('.csv');
        setIsUploading(true);
        try {
            // Dentro del try: un fichero ilegible (borrado, sin permisos) avisa en vez de no hacer nada.
            const text = await file.text();
            const result = isCsv
                ? await importIBKRCsv(userId, text)
                : await importIBKRXml(userId, text);
            if (!notifyImportResult(result, ti, f)) return;
            router.refresh();
        } catch (error) {
            showErrorToast(error);
        } finally {
            setIsUploading(false);
        }
    }

    const busy = isImporting || isUploading;

    return (
        <>
            <input
                ref={fileInputRef}
                type="file"
                accept=".xml,.csv"
                className="hidden"
                onChange={handleFile}
            />
            <Button
                variant="outline"
                size="sm"
                onClick={handleImport}
                disabled={busy}
                aria-busy={isImporting}
                className="border-gray-600 hover:bg-gray-700 text-gray-200"
                title={ti('portfolio.importIbk.importTitle')}
            >
                {isImporting ? (
                    <>
                        <Loader2 aria-hidden="true" className="mr-2 h-4 w-4 animate-spin" />
                        {ti('portfolio.importIbk.importing')}
                    </>
                ) : (
                    <>
                        <Landmark aria-hidden="true" className="mr-2 h-4 w-4" />
                        {ti('portfolio.importIbk.importCta')}
                    </>
                )}
            </Button>
            <Button
                variant="outline"
                size="sm"
                onClick={() => fileInputRef.current?.click()}
                disabled={busy}
                aria-busy={isUploading}
                className="border-gray-600 hover:bg-gray-700 text-gray-200"
                title={ti('portfolio.importIbk.uploadTitle')}
            >
                {isUploading ? (
                    <>
                        <Loader2 aria-hidden="true" className="mr-2 h-4 w-4 animate-spin" />
                        {ti('portfolio.importIbk.uploading')}
                    </>
                ) : (
                    <>
                        <Upload aria-hidden="true" className="mr-2 h-4 w-4" />
                        {ti('portfolio.importIbk.uploadCta')}
                    </>
                )}
            </Button>
        </>
    );
}
