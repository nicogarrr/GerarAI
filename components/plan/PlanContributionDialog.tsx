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
import { formatNumberForInput, parseLocalizedNumber, todayLocal } from '@/lib/format';

const CURRENCY_OPTIONS = ['EUR', 'USD', 'GBP', 'CHF', 'JPY'];

/** Valida el formulario de aportación; devuelve el error en es-ES o null. */
export function contributionFormError(input: { date: string; amount: number | null; today: string }): string | null {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(input.date)) return 'Indica la fecha de la aportación.';
    if (input.date > input.today) return 'La fecha no puede ser futura: registra la aportación cuando la hagas.';
    if (input.amount === null || !Number.isFinite(input.amount) || input.amount < 0.01) {
        return 'El importe debe ser mayor que 0 (mínimo 0,01).';
    }
    if (input.amount > 10_000_000) return 'El importe no puede superar 10.000.000.';
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
    const initialCurrency = (defaultCurrency ?? '').toUpperCase() || 'EUR';
    const [open, setOpen] = useState(false);
    const [pending, setPending] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [date, setDate] = useState(() => todayLocal());
    const [amount, setAmount] = useState(() =>
        typeof defaultAmount === 'number' && defaultAmount > 0 ? formatNumberForInput(defaultAmount) : '',
    );
    const [currency, setCurrency] = useState(initialCurrency);
    const [note, setNote] = useState('');
    const currencies = CURRENCY_OPTIONS.includes(initialCurrency) ? CURRENCY_OPTIONS : [initialCurrency, ...CURRENCY_OPTIONS];

    const handleSubmit = async (event: React.FormEvent) => {
        event.preventDefault();
        const parsed = parseLocalizedNumber(amount);
        const problem = contributionFormError({ date, amount: parsed, today: todayLocal() });
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
            toast.success('Aportación registrada');
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
                    Registrar aportación
                </Button>
            </DialogTrigger>
            <DialogContent className="border-gray-700 bg-gray-900 text-gray-100 sm:max-w-md">
                <DialogHeader>
                    <DialogTitle>Registrar aportación</DialogTitle>
                    <DialogDescription className="text-gray-400">
                        Anota el dinero que has aportado al plan. Sirve para saber si vas al día con tu cuota; no realiza ninguna orden.
                    </DialogDescription>
                </DialogHeader>
                <form onSubmit={handleSubmit} className="space-y-4" noValidate>
                    <div className="grid gap-4 sm:grid-cols-2">
                        <div className="space-y-1.5">
                            <Label htmlFor="contribution-date" className="text-gray-300">Fecha</Label>
                            <Input id="contribution-date" type="date" value={date} max={todayLocal()} onChange={(e) => setDate(e.target.value)} />
                        </div>
                        <div className="space-y-1.5">
                            <Label htmlFor="contribution-amount" className="text-gray-300">Importe</Label>
                            <Input id="contribution-amount" inputMode="decimal" autoComplete="off" placeholder="300,00" value={amount} onChange={(e) => setAmount(e.target.value)} />
                        </div>
                    </div>
                    <div className="space-y-1.5">
                        <Label htmlFor="contribution-currency" className="text-gray-300">Divisa</Label>
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
                        <Label htmlFor="contribution-note" className="text-gray-300">Nota (opcional)</Label>
                        <Input id="contribution-note" maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Transferencia de octubre" />
                    </div>
                    {error ? <p role="alert" className="text-sm text-red-400">{error}</p> : null}
                    <div className="flex justify-end gap-2">
                        <Button type="button" variant="outline" onClick={() => setOpen(false)}>Cancelar</Button>
                        <Button type="submit" disabled={pending}>{pending ? 'Guardando…' : 'Guardar aportación'}</Button>
                    </div>
                </form>
            </DialogContent>
        </Dialog>
    );
}
