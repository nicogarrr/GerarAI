'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { PiggyBank } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { addPlanContribution } from '@/lib/actions/plan.actions';
import { todayLocal } from '@/lib/format';
import { parseLocalizedNumber } from '@/lib/i18n/parse-number';
import esPlan from '@/lib/i18n/messages/es/plan.json';
import { useFormat, useLocale, useT } from '@/lib/i18n/client';

const CURRENCY_OPTIONS = ['EUR', 'USD', 'GBP', 'CHF', 'JPY'];

type ContributionErrorKey =
    | 'plan.contribution.errorDateMissing'
    | 'plan.contribution.errorDateFuture'
    | 'plan.contribution.errorAmountMin'
    | 'plan.contribution.errorAmountMax';
type PlanT = (key: ContributionErrorKey) => string;

/** t() de respaldo en es-ES para quien llame al validador fuera de React. */
const esFallbackT: PlanT = (key) => {
    const node = key.replace(/^plan\.contribution\./, '').split('.').reduce<unknown>(
        (acc, part) => (acc !== null && typeof acc === 'object' ? (acc as Record<string, unknown>)[part] : undefined),
        esPlan.contribution,
    );
    return typeof node === 'string' ? node : key;
};

/** Valida el formulario de aportación; devuelve el error traducido o null. */
export function contributionFormError(
    input: { date: string; amount: number | null; today: string },
    t: PlanT = esFallbackT,
): string | null {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(input.date)) return t('plan.contribution.errorDateMissing');
    if (input.date > input.today) return t('plan.contribution.errorDateFuture');
    if (input.amount === null || !Number.isFinite(input.amount) || input.amount < 0.01) {
        return t('plan.contribution.errorAmountMin');
    }
    if (input.amount > 10_000_000) return t('plan.contribution.errorAmountMax');
    return null;
}

/**
 * Registrar una aportación al plan. Sin esta vía la UI solo leía el historial:
 * «Aportaciones reales», «Desviación» y «En camino» nunca se podían rellenar.
 * Precarga la cuota del plan, su divisa (o la base) y la fecha de hoy.
 */
export default function PlanContributionDialog({
    defaultAmount,
    defaultCurrency,
}: {
    defaultAmount?: number | null;
    defaultCurrency?: string | null;
}) {
    const router = useRouter();
    const t = useT();
    const f = useFormat();
    const locale = useLocale();
    const initialCurrency = (defaultCurrency ?? '').toUpperCase() || 'EUR';
    const [open, setOpen] = useState(false);
    const [pending, setPending] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [date, setDate] = useState(() => todayLocal());
    const [amount, setAmount] = useState(() =>
        typeof defaultAmount === 'number' && defaultAmount > 0 ? f.formatNumberForInput(defaultAmount) : '',
    );
    const [currency, setCurrency] = useState(initialCurrency);
    const [note, setNote] = useState('');
    const currencies = CURRENCY_OPTIONS.includes(initialCurrency) ? CURRENCY_OPTIONS : [initialCurrency, ...CURRENCY_OPTIONS];

    const handleSubmit = async (event: React.FormEvent) => {
        event.preventDefault();
        const parsed = parseLocalizedNumber(amount, locale);
        const problem = contributionFormError({ date, amount: parsed, today: todayLocal() }, t);
        if (problem) {
            setError(problem);
            return;
        }
        setError(null);
        setPending(true);
        try {
            const result = await addPlanContribution({ date, amount: parsed as number, currency, note: note.trim() });
            if (!result.ok) {
                setError(result.message);
                return;
            }
            toast.success(t('plan.contribution.savedToast'));
            setOpen(false);
            setNote('');
            router.refresh();
        } finally {
            setPending(false);
        }
    };

    return (
        <Dialog open={open} onOpenChange={(next) => { setOpen(next); if (!next) setError(null); }}>
            <DialogTrigger asChild>
                <Button type="button" className="min-h-[44px] gap-2">
                    <PiggyBank className="h-4 w-4" aria-hidden="true" />
                    {t('plan.contribution.trigger')}
                </Button>
            </DialogTrigger>
            <DialogContent className="border-gray-700 bg-gray-900 text-gray-100 sm:max-w-md">
                <DialogHeader>
                    <DialogTitle>{t('plan.contribution.title')}</DialogTitle>
                    <DialogDescription className="text-gray-400">
                        {t('plan.contribution.description')}
                    </DialogDescription>
                </DialogHeader>
                <form onSubmit={handleSubmit} className="space-y-4" noValidate>
                    <div className="grid gap-4 sm:grid-cols-2">
                        <div className="space-y-1.5">
                            <Label htmlFor="contribution-date" className="text-gray-300">{t('plan.contribution.dateLabel')}</Label>
                            <Input id="contribution-date" type="date" value={date} max={todayLocal()} onChange={(e) => setDate(e.target.value)} />
                        </div>
                        <div className="space-y-1.5">
                            <Label htmlFor="contribution-amount" className="text-gray-300">{t('plan.contribution.amountLabel')}</Label>
                            <Input id="contribution-amount" inputMode="decimal" autoComplete="off" placeholder={t('plan.contribution.amountPlaceholder')} value={amount} onChange={(e) => setAmount(e.target.value)} />
                        </div>
                    </div>
                    <div className="space-y-1.5">
                        <Label htmlFor="contribution-currency" className="text-gray-300">{t('plan.contribution.currencyLabel')}</Label>
                        <select
                            id="contribution-currency"
                            className="h-11 w-full rounded-md border border-gray-700 bg-gray-800 px-3 text-sm text-gray-100"
                            value={currency}
                            onChange={(e) => setCurrency(e.target.value)}
                        >
                            {currencies.map((code) => <option key={code} value={code}>{code}</option>)}
                        </select>
                    </div>
                    <div className="space-y-1.5">
                        <Label htmlFor="contribution-note" className="text-gray-300">{t('plan.contribution.noteLabel')}</Label>
                        <Input id="contribution-note" maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} placeholder={t('plan.contribution.notePlaceholder')} />
                    </div>
                    {error ? <p role="alert" className="text-sm text-red-400">{error}</p> : null}
                    <div className="flex justify-end gap-2">
                        <Button type="button" variant="outline" onClick={() => setOpen(false)}>{t('plan.contribution.cancel')}</Button>
                        <Button type="submit" disabled={pending}>{pending ? t('plan.contribution.saving') : t('plan.contribution.save')}</Button>
                    </div>
                </form>
            </DialogContent>
        </Dialog>
    );
}
