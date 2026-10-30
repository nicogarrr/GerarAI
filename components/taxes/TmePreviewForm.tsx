'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { previewTaxFiling, type TaxRecord } from '@/lib/actions/taxes.actions';
import { parseLocalizedNumber } from '@/lib/format';
import { showErrorToast } from '@/lib/toast';

export default function TmePreviewForm({ year, onPreview, onReset }: {
    year: number;
    onPreview: (report: TaxRecord) => void;
    onReset: () => void;
}) {
    const [input, setInput] = useState('');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [applied, setApplied] = useState(false);

    async function submit(event: React.FormEvent<HTMLFormElement>) {
        event.preventDefault();
        const percent = parseLocalizedNumber(input);
        if (percent === null || percent < 0 || percent > 100 || Math.abs(percent * 100 - Math.round(percent * 100)) > 0.000001) {
            setError('Introduce el TME de tu borrador entre 0 y 100 %, con un máximo de dos decimales.');
            return;
        }
        setError(null);
        setBusy(true);
        try {
            onPreview(await previewTaxFiling(year, percent));
            setApplied(true);
        } catch (cause) {
            showErrorToast(cause);
        } finally {
            setBusy(false);
        }
    }

    return (
        <form onSubmit={submit} className="mt-4 space-y-2 border-t border-gray-800 pt-4">
            <label htmlFor="tax-tme" className="block text-sm text-gray-300">TME de la base liquidable del ahorro (%)</label>
            <div className="flex flex-wrap items-center gap-2">
                <input id="tax-tme" value={input} onChange={(event) => { setInput(event.target.value); setError(null); }}
                    inputMode="decimal" placeholder="Ej. 19,00" disabled={busy}
                    aria-invalid={Boolean(error)} aria-describedby={error ? 'tax-tme-error' : 'tax-tme-note'}
                    className="h-9 w-32 rounded-md border border-gray-700 bg-black px-3 text-sm text-gray-100" />
                <Button type="submit" size="sm" disabled={busy}>{busy ? 'Calculando…' : 'Calcular vista previa'}</Button>
                {applied && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => {
                    onReset(); setApplied(false); setInput('');
                }}>Quitar TME</Button>}
            </div>
            <p id="tax-tme-note" className="text-xs text-gray-500">
                Solo para {year}. No se guarda ni sustituye tu declaración. Usa el tipo medio efectivo de la base liquidable del ahorro (como lo calcula Hacienda: cuota líquida total × cuota íntegra del ahorro ÷ cuota íntegra total, dividido entre la base liquidable del ahorro, por 100, con dos decimales; GerarAI lo aplica al dividendo íntegro de cada país), no el de la base general ni el de toda la declaración. Fuente: Agencia Tributaria, Manual Renta 2025, capítulo 18, deducción por doble imposición internacional.
            </p>
            {error && <p id="tax-tme-error" role="alert" className="text-xs text-amber-300">{error}</p>}
        </form>
    );
}
