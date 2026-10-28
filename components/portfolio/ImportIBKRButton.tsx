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

export default function ImportIBKRButton({ userId }: ImportIBKRButtonProps) {
    const [isImporting, setIsImporting] = useState(false);
    const [isUploading, setIsUploading] = useState(false);
    const fileInputRef = useRef<HTMLInputElement>(null);
    const router = useRouter();

    async function handleImport() {
        try {
            setIsImporting(true);
            const result = await importFromIBKR(userId);

            if (result.status !== 'imported') {
                toast.error(result.message ?? `Importación falló: ${result.status}`, { duration: 10000 });
                return;
            }

            toast.success(describeResult(result));
            if (result.identity_warning) toast.warning(result.identity_warning);
            if (result.row_errors?.length) {
                toast.warning(`Filas con avisos:\n${result.row_errors.slice(0, 3).join('\n')}`);
            }
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
        const text = await file.text();
        const isCsv = file.name.toLowerCase().endsWith('.csv');
        setIsUploading(true);
        try {
            const result = isCsv
                ? await importIBKRCsv(userId, text)
                : await importIBKRXml(userId, text);
            if (result.status !== 'imported') {
                toast.error(result.message ?? `Importación falló: ${result.status}`, { duration: 10000 });
                return;
            }
            toast.success(describeResult(result));
            if (result.identity_warning) toast.warning(result.identity_warning);
            if (result.row_errors?.length) {
                toast.warning(
                    `${plural(result.row_errors.length, 'fila con avisos', 'filas con avisos')}. Primera: ${result.row_errors[0]}`,
                    { duration: 8000 }
                );
            }
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
