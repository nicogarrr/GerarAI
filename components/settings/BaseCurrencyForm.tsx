'use client';

import { useState } from 'react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select';
import {
    savePortfolioBaseCurrency,
    type PortfolioCurrencySettings,
} from '@/lib/actions/portfolio-settings.actions';
import { formatDate } from '@/lib/format';
import { showErrorToast } from '@/lib/toast';

// Divisas con tipo de referencia diario del BCE.
const CURRENCIES = [
    { value: 'EUR', label: 'EUR · Euro' },
    { value: 'USD', label: 'USD · Dólar estadounidense' },
    { value: 'GBP', label: 'GBP · Libra esterlina' },
    { value: 'CHF', label: 'CHF · Franco suizo' },
    { value: 'JPY', label: 'JPY · Yen japonés' },
    { value: 'CAD', label: 'CAD · Dólar canadiense' },
    { value: 'DKK', label: 'DKK · Corona danesa' },
    { value: 'SEK', label: 'SEK · Corona sueca' },
    { value: 'NOK', label: 'NOK · Corona noruega' },
    { value: 'HKD', label: 'HKD · Dólar de Hong Kong' },
] as const;

export default function BaseCurrencyForm({ initial }: { initial: PortfolioCurrencySettings }) {
    const initialCurrency = (initial.base_currency || 'EUR').toUpperCase();
    const [saved, setSaved] = useState(initialCurrency);
    const [currency, setCurrency] = useState(initialCurrency);
    const [saving, setSaving] = useState(false);
    const known = CURRENCIES.some((option) => option.value === currency);
    const fx = initial.fx_source;

    const save = async () => {
        setSaving(true);
        try {
            const result = await savePortfolioBaseCurrency(currency);
            setSaved(result.base_currency);
            toast.success(`Divisa base: ${result.base_currency}. Cartera revalorada.`);
        } catch (error) {
            showErrorToast(error);
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-end gap-3">
                <label className="flex flex-col gap-1 text-sm text-gray-300">
                    Divisa base
                    <Select value={currency} onValueChange={setCurrency}>
                        <SelectTrigger className="w-64 data-[size=default]:h-11" aria-label="Divisa base">
                            <SelectValue placeholder="EUR" />
                        </SelectTrigger>
                        <SelectContent>
                            {!known ? <SelectItem value={currency}>{currency}</SelectItem> : null}
                            {CURRENCIES.map((option) => (
                                <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </label>
                <Button disabled={saving || currency === saved} onClick={save} type="button">
                    {saving ? 'Guardando…' : 'Guardar'}
                </Button>
            </div>
            <p className="text-xs text-gray-400">
                La cartera y sus totales se muestran en esta divisa, y la G/P se separa en efecto precio y efecto divisa.
                Cada valor se sigue mostrando en la divisa en que cotiza. Las operaciones se guardan en su divisa original
                y se convierten al leerlas, así que cambiar la base no reescribe nada. IRPF y Modelo 720 van siempre en EUR al tipo del BCE.
            </p>
            <p className="text-xs text-gray-500">
                Tipos de cambio: {fx?.source ?? 'BCE'}
                {fx?.latest_rate_date ? `, último del ${formatDate(fx.latest_rate_date)}` : ', sin tipos descargados todavía'}.
            </p>
        </div>
    );
}
