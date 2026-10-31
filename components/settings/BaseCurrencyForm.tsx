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
import { useFormat, useT } from '@/lib/i18n/client';
import { showErrorToast } from '@/lib/toast';

// Divisas con tipo de referencia diario del BCE.
const CURRENCIES = [
    { value: 'EUR', name: 'settings.currency.names.EUR' },
    { value: 'USD', name: 'settings.currency.names.USD' },
    { value: 'GBP', name: 'settings.currency.names.GBP' },
    { value: 'CHF', name: 'settings.currency.names.CHF' },
    { value: 'JPY', name: 'settings.currency.names.JPY' },
    { value: 'CAD', name: 'settings.currency.names.CAD' },
    { value: 'DKK', name: 'settings.currency.names.DKK' },
    { value: 'SEK', name: 'settings.currency.names.SEK' },
    { value: 'NOK', name: 'settings.currency.names.NOK' },
    { value: 'HKD', name: 'settings.currency.names.HKD' },
] as const;

export default function BaseCurrencyForm({ initial }: { initial: PortfolioCurrencySettings }) {
    const initialCurrency = (initial.base_currency || 'EUR').toUpperCase();
    const [saved, setSaved] = useState(initialCurrency);
    const [currency, setCurrency] = useState(initialCurrency);
    const [saving, setSaving] = useState(false);
    const known = CURRENCIES.some((option) => option.value === currency);
    const fx = initial.fx_source;
    const t = useT();
    const { formatDate } = useFormat();

    const save = async () => {
        setSaving(true);
        try {
            const result = await savePortfolioBaseCurrency(currency);
            setSaved(result.base_currency);
            toast.success(t('settings.currency.saved', { currency: result.base_currency }));
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
                    {t('settings.currency.label')}
                    <Select value={currency} onValueChange={setCurrency}>
                        <SelectTrigger className="w-64 data-[size=default]:h-11" aria-label={t('settings.currency.label')}>
                            <SelectValue placeholder="EUR" />
                        </SelectTrigger>
                        <SelectContent>
                            {!known ? <SelectItem value={currency}>{currency}</SelectItem> : null}
                            {CURRENCIES.map((option) => (
                                <SelectItem key={option.value} value={option.value}>{option.value} · {t(option.name)}</SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </label>
                <Button disabled={saving || currency === saved} onClick={save} type="button">
                    {saving ? t('settings.common.saving') : t('settings.common.save')}
                </Button>
            </div>
            <details className="text-xs text-gray-400">
                <summary className="min-h-11 cursor-pointer py-3 text-teal-300">{t('settings.currency.howTitle')}</summary>
                <p className="pb-2 leading-relaxed">
                {t('settings.currency.howBody')}
                </p>
            </details>
            <p className="text-xs text-gray-500">
                {t('settings.currency.fxSource', { source: fx?.source ?? t('settings.currency.ecb') })}
                {fx?.latest_rate_date ? t('settings.currency.fxLatest', { date: formatDate(fx.latest_rate_date) }) : t('settings.currency.fxNone')}
            </p>
        </div>
    );
}
