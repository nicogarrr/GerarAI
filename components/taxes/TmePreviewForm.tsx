'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { previewTaxFiling, type TaxRecord } from '@/lib/actions/taxes.actions';
import { parseLocalizedNumber } from '@/lib/i18n/parse-number';
import { useT, useLocale } from '@/lib/i18n/client';
import { showErrorToast } from '@/lib/toast';

export default function TmePreviewForm({ year, onPreview, onReset }: {
    year: number;
    onPreview: (report: TaxRecord) => void;
    onReset: () => void;
}) {
    const t = useT();
    const locale = useLocale();
    const [input, setInput] = useState('');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [applied, setApplied] = useState(false);

    async function submit(event: React.FormEvent<HTMLFormElement>) {
        event.preventDefault();
        const percent = parseLocalizedNumber(input, locale);
        if (percent === null || percent < 0 || percent > 100 || Math.abs(percent * 100 - Math.round(percent * 100)) > 0.000001) {
            setError(t('taxes.tme.errorInvalid'));
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
            <label htmlFor="tax-tme" className="block text-sm text-gray-300">{t('taxes.tme.label')}</label>
            <div className="flex flex-wrap items-center gap-2">
                <input id="tax-tme" value={input} onChange={(event) => { setInput(event.target.value); setError(null); }}
                    inputMode="decimal" placeholder={t('taxes.tme.placeholder')} disabled={busy}
                    aria-invalid={Boolean(error)} aria-describedby={error ? 'tax-tme-error' : 'tax-tme-note'}
                    className="h-9 w-32 rounded-md border border-gray-700 bg-black px-3 text-sm text-gray-100" />
                <Button type="submit" size="sm" disabled={busy}>{busy ? t('taxes.tme.calculating') : t('taxes.tme.calculate')}</Button>
                {applied && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => {
                    onReset(); setApplied(false); setInput('');
                }}>{t('taxes.tme.remove')}</Button>}
            </div>
            <p id="tax-tme-note" className="text-xs text-gray-500">
                {t('taxes.tme.note', { year })}
            </p>
            {error && <p id="tax-tme-error" role="alert" className="text-xs text-amber-300">{error}</p>}
        </form>
    );
}
