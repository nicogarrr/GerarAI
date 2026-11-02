'use client';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useT } from '@/lib/i18n/client';
import { currencyOptions } from './transactionCurrencies';
import type { TransactionFormErrors } from './transactionValidation';

/**
 * Campos de una operación (divisa, tipo, cantidad, precio, comisión, fecha,
 * notas y pie con cancelar/guardar) compartidos por el alta
 * (AddTransactionDialog) y la edición (EditTransactionDialog). Hasta ahora
 * cada diálogo llevaba su copia y los arreglos había que hacerlos dos veces.
 */
export type TransactionFormFieldsData = {
    currency: string;
    type: 'buy' | 'sell';
    quantity: string;
    price: string;
    fees: string;
    date: string;
    notes: string;
};

type Props = {
    formData: TransactionFormFieldsData;
    onPatch: (patch: Partial<TransactionFormFieldsData>) => void;
    fieldErrors: TransactionFormErrors;
    /** En edición los ids van prefijados («edit-currency», «edit-fees»). */
    currencyId: string;
    feesId: string;
    /** Alta: la divisa elegida a mano se fija aunque cambie el ticker. Por defecto solo escribe el campo. */
    onCurrencyChange?: (currency: string) => void;
    /** Solo el alta lleva placeholders de ejemplo en cantidad/precio. */
    quantityPlaceholder?: string;
    pricePlaceholder?: string;
    /** Solo el alta lleva placeholder de ejemplo en las notas. */
    notesPlaceholder?: string;
    onCancel: () => void;
    saveLabel: string;
    loading: boolean;
    /** Edición: el submit anuncia aria-busy mientras guarda. */
    busy?: boolean;
};

export function TransactionFormFields({
    formData,
    onPatch,
    fieldErrors,
    currencyId,
    feesId,
    onCurrencyChange,
    quantityPlaceholder,
    pricePlaceholder,
    notesPlaceholder,
    onCancel,
    saveLabel,
    loading,
    busy,
}: Props) {
    const ti = useT();
    return (
        <>
            <div className="space-y-2">
                <Label htmlFor={currencyId} className="text-gray-300">{ti('portfolio.addTransaction.currencyLabel')}</Label>
                <Select value={formData.currency} onValueChange={(currency) => (onCurrencyChange ? onCurrencyChange(currency) : onPatch({ currency }))}>
                    <SelectTrigger id={currencyId} className="bg-gray-800 border-gray-700 text-gray-100"><SelectValue /></SelectTrigger>
                    <SelectContent className="bg-gray-800 border-gray-700">
                        {currencyOptions(formData.currency).map((currency) => <SelectItem value={currency} key={currency}>{currency}</SelectItem>)}
                    </SelectContent>
                </Select>
            </div>

            <div className="space-y-2">
                <Label htmlFor="type" className="text-gray-300">{ti('portfolio.addTransaction.typeLabel')}</Label>
                <Select
                    value={formData.type}
                    onValueChange={(value: 'buy' | 'sell') => onPatch({ type: value })}
                >
                    <SelectTrigger className="bg-gray-800 border-gray-700 text-gray-100">
                        <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="bg-gray-800 border-gray-700">
                        <SelectItem value="buy">{ti('portfolio.addTransaction.typeBuy')}</SelectItem>
                        <SelectItem value="sell">{ti('portfolio.addTransaction.typeSell')}</SelectItem>
                    </SelectContent>
                </Select>
            </div>

            <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                    <Label htmlFor="quantity" className="text-gray-300">{ti('portfolio.addTransaction.quantityLabel')}</Label>
                    <Input
                        id="quantity"
                        type="text"
                        inputMode="decimal"
                        placeholder={quantityPlaceholder}
                        value={formData.quantity}
                        onChange={(e) => onPatch({ quantity: e.target.value })}
                        required
                        className="bg-gray-800 border-gray-700 text-gray-100"
                    />
                    {fieldErrors.quantity && (
                        <p role="alert" className="text-sm text-red-400">{fieldErrors.quantity}</p>
                    )}
                </div>

                <div className="space-y-2">
                    <Label htmlFor="price" className="text-gray-300">{ti('portfolio.addTransaction.priceLabel', { currency: formData.currency })}</Label>
                    <Input
                        id="price"
                        type="text"
                        inputMode="decimal"
                        placeholder={pricePlaceholder}
                        value={formData.price}
                        onChange={(e) => onPatch({ price: e.target.value })}
                        required
                        className="bg-gray-800 border-gray-700 text-gray-100"
                    />
                    {fieldErrors.price && (
                        <p role="alert" className="text-sm text-red-400">{fieldErrors.price}</p>
                    )}
                </div>
            </div>

            <div className="space-y-2">
                <Label htmlFor={feesId} className="text-gray-300">{ti('portfolio.addTransaction.feesLabel', { currency: formData.currency })}</Label>
                <Input
                    id={feesId}
                    type="text"
                    inputMode="decimal"
                    placeholder={ti('portfolio.addTransaction.feesPlaceholder')}
                    value={formData.fees}
                    onChange={(e) => onPatch({ fees: e.target.value })}
                    className="bg-gray-800 border-gray-700 text-gray-100"
                />
                {fieldErrors.fees && (
                    <p role="alert" className="text-sm text-red-400">{fieldErrors.fees}</p>
                )}
            </div>

            <div className="space-y-2">
                <Label htmlFor="date" className="text-gray-300">{ti('portfolio.addTransaction.dateLabel')}</Label>
                <Input
                    id="date"
                    type="date"
                    value={formData.date}
                    onChange={(e) => onPatch({ date: e.target.value })}
                    required
                    className="bg-gray-800 border-gray-700 text-gray-100"
                />
                {fieldErrors.date && (
                    <p role="alert" className="text-sm text-red-400">{fieldErrors.date}</p>
                )}
            </div>

            <div className="space-y-2">
                <Label htmlFor="notes" className="text-gray-300">{ti('portfolio.addTransaction.notesLabel')}</Label>
                <Input
                    id="notes"
                    placeholder={notesPlaceholder}
                    value={formData.notes}
                    onChange={(e) => onPatch({ notes: e.target.value })}
                    className="bg-gray-800 border-gray-700 text-gray-100"
                />
            </div>

            <div className="flex justify-end gap-2 pt-2">
                <Button type="button" variant="outline" onClick={onCancel}>
                    {ti('common.actions.cancel')}
                </Button>
                <Button
                    type="submit"
                    disabled={loading}
                    {...(busy ? { 'aria-busy': loading } : {})}
                >
                    {loading ? ti('portfolio.addTransaction.saving') : saveLabel}
                </Button>
            </div>
        </>
    );
}
