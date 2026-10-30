'use client';

import { useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Loader2, Landmark, Upload } from 'lucide-react';
import { importFromIBKR, importIBKRCsv, importIBKRXml } from '@/lib/actions/portfolio.actions';
import { formatNumber } from '@/lib/format';
import { toast } from 'sonner';
import { showErrorToast } from '@/lib/toast';

interface ImportIBKRButtonProps {
    userId: string;
}

type ImportCounts = {
    status: string;
    rows_skipped?: number;
    row_errors?: string[];
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

function count(value: number): string {
    return formatNumber(value, { maximumFractionDigits: 0 });
}

/** Concordancia es-ES: «1 posición» / «2 posiciones». Un solo literal por par. */
function plural(n: number, singular: string, pluralForm: string): string {
    return `${count(n)} ${n === 1 ? singular : pluralForm}`;
}

export function describeResult(result: ImportCounts): string {
    const parts: string[] = [];
    const positions = num(result.positions_imported);
    if (positions !== null) {
        const trades = num(result.trades_imported) ?? 0;
        const dividends = num(result.dividends_imported) ?? 0;
        const fees = num(result.fees_imported) ?? 0;
        const cash = num(result.cash_imported) ?? 0;
        parts.push(
            `IBKR: ${plural(positions, 'posición', 'posiciones')}, ` +
            `${plural(trades, 'operación', 'operaciones')}, ` +
            `${plural(dividends, 'dividendo', 'dividendos')}, ` +
            `${plural(fees, 'comisión', 'comisiones')}, ` +
            `${plural(cash, 'cuenta de efectivo', 'cuentas de efectivo')}`
        );
    } else {
        const trades = num(result.trades_imported) ?? 0;
        parts.push(`IBKR CSV: ${plural(trades, 'operación importada', 'operaciones importadas')}`);
    }
    const duplicates = num(result.duplicate_trades) ?? 0;
    if (duplicates > 0) {
        parts.push(plural(duplicates, 'operación ya importada', 'operaciones ya importadas'));
    }
    if (result.rows_skipped) {
        parts.push(plural(result.rows_skipped, 'fila omitida', 'filas omitidas'));
    }
    return parts.join(' · ');
}

/**
 * Las subidas viajan como argumento de una server action, cuyo cuerpo está
 * limitado a 4 MB (next.config.ts). Con margen para la serialización, un
 * fichero mayor fallaba con un error genérico tras subirlo entero.
 */
export const MAX_UPLOAD_BYTES = 3.5 * 1024 * 1024;

function megabytes(bytes: number): string {
    return `${formatNumber(bytes / (1024 * 1024), { maximumFractionDigits: 1 })} MB`;
}

/** Motivo para no enviar el fichero, o null si se puede subir. */
export function uploadProblem(file: { size: number }): string | null {
    if (file.size === 0) return 'El fichero está vacío.';
    if (file.size > MAX_UPLOAD_BYTES) {
        return `El fichero pesa ${megabytes(file.size)} y el máximo es ${megabytes(MAX_UPLOAD_BYTES)}. ` +
            'Exporta un periodo más corto o divídelo en varios ficheros.';
    }
    return null;
}

const ROW_ERRORS_SHOWN = 5;

/** Detalle de las filas con avisos: hasta 5, y cuántas quedan. */
export function rowErrorDetail(errors: string[]): string {
    const shown = errors.slice(0, ROW_ERRORS_SHOWN).join('\n');
    const rest = errors.length - ROW_ERRORS_SHOWN;
    return rest > 0 ? `${shown}\n${plural(rest, 'aviso más', 'avisos más')}` : shown;
}

type ImportOutcome = ImportCounts & { message?: string | null };

/**
 * Avisos del resultado de una importación (Flex o fichero), los mismos en las
 * dos vías. Antes la vía Flex enseñaba solo 3 avisos sin decir cuántos había y
 * el fallo sin motivo salía como «Importación falló: rejected».
 * Devuelve true si se importó.
 */
export function notifyImportResult(result: ImportOutcome): boolean {
    if (result.status !== 'imported') {
        toast.error(result.message || 'La importación no se completó. Revisa el fichero o la conexión con IBKR e inténtalo de nuevo.', { duration: 10000 });
        return false;
    }
    toast.success(describeResult(result));
    if (result.identity_warning) toast.warning(result.identity_warning);
    if (result.row_errors?.length) {
        toast.warning(
            `${plural(result.row_errors.length, 'fila con avisos', 'filas con avisos')}. Primera: ${result.row_errors[0]}`,
            { duration: 12000, description: rowErrorDetail(result.row_errors) }
        );
    }
    return true;
}

export default function ImportIBKRButton({ userId }: ImportIBKRButtonProps) {
    const [isImporting, setIsImporting] = useState(false);
    const [isUploading, setIsUploading] = useState(false);
    const fileInputRef = useRef<HTMLInputElement>(null);
    const router = useRouter();

    async function handleImport() {
        try {
            setIsImporting(true);
            const result = await importFromIBKR(userId);
            if (!notifyImportResult(result)) return;
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
        const problem = uploadProblem(file);
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
            if (!notifyImportResult(result)) return;
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
                title="Importar cartera desde Interactive Brokers (Flex statement)"
            >
                {isImporting ? (
                    <>
                        <Loader2 aria-hidden="true" className="mr-2 h-4 w-4 animate-spin" />
                        Importando IBKR...
                    </>
                ) : (
                    <>
                        <Landmark aria-hidden="true" className="mr-2 h-4 w-4" />
                        Importar IBKR
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
                title="CSV con cabecera symbol, action, quantity, price, date (opcionales fees, currency) o Flex XML de IBKR"
            >
                {isUploading ? (
                    <>
                        <Loader2 aria-hidden="true" className="mr-2 h-4 w-4 animate-spin" />
                        Subiendo...
                    </>
                ) : (
                    <>
                        <Upload aria-hidden="true" className="mr-2 h-4 w-4" />
                        Subir fichero
                    </>
                )}
            </Button>
        </>
    );
}
