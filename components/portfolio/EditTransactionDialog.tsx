'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
} from '@/components/ui/dialog';
import { TickerSearchInput } from '@/components/search/TickerSearchInput';
import { Pencil } from 'lucide-react';
import { updateTransaction, type PortfolioTransaction } from '@/lib/actions/portfolio.actions';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import { showErrorToast } from '@/lib/toast';
import { isNextRedirectError } from '@/lib/types/errors';
import { hasTransactionErrors, validateTransactionForm, type TransactionFormErrors } from './transactionValidation';
import { TransactionFormFields } from './TransactionFormFields';
import { parseLocalizedNumber } from '@/lib/i18n/parse-number';
import { useFormat, useLocale, useT } from '@/lib/i18n/client';
import type { Formatters } from '@/lib/format';


type Props = {
    transaction: PortfolioTransaction;
    userId: string;
};

function initialForm(transaction: PortfolioTransaction, f: Formatters) {
    return {
        symbol: transaction.symbol,
        type: transaction.type,
        quantity: f.formatNumberForInput(transaction.quantity),
        price: f.formatNumberForInput(transaction.price),
        // Sin dato de comisión en la fila el campo queda vacío: guardar sin tocarlo OMITE fees y el backend conserva la registrada (nunca se resetea a 0).
        fees: transaction.fees === undefined ? '' : f.formatNumberForInput(transaction.fees),
        date: transaction.date.slice(0, 10),
        notes: transaction.notes || '',
        // La divisa guardada se conserva aunque no esté en la lista corta
        // (SEK, DKK, NOK… de IBKR): antes el selector salía en blanco.
        currency: transaction.currency || 'USD',
    };
}

export default function EditTransactionDialog({ transaction, userId }: Props) {
    const ti = useT();
    const locale = useLocale();
    const f = useFormat();
    const router = useRouter();
    const [open, setOpen] = useState(false);
    const [loading, setLoading] = useState(false);
    const [fieldErrors, setFieldErrors] = useState<TransactionFormErrors>({});

    const [formData, setFormData] = useState(() => initialForm(transaction, f));
    // Cada apertura parte de lo guardado: antes, cancelar tras tocar campos
    // dejaba esos cambios sin guardar en el formulario y al reabrirlo parecían
    // los datos reales del movimiento.
    const handleOpenChange = (next: boolean) => {
        if (next) {
            setFormData(initialForm(transaction, f));
            setFieldErrors({});
        }
        setOpen(next);
    };

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        const errors = validateTransactionForm(formData, new Date(), { ti, locale });
        setFieldErrors(errors);
        if (hasTransactionErrors(errors)) return;
        setLoading(true);

        try {
            const result = await updateTransaction(
                userId,
                transaction._id,
                formData.symbol,
                formData.type,
                parseLocalizedNumber(formData.quantity, locale) ?? 0,
                parseLocalizedNumber(formData.price, locale) ?? 0,
                new Date(formData.date),
                formData.notes || undefined,
                formData.currency,
                // Sin dato de comisión en la fila no se envía (el backend conserva la registrada).
                transaction.fees === undefined && formData.fees.trim() === ''
                    ? undefined
                    : (parseLocalizedNumber(formData.fees, locale) ?? 0),
            );
            // Rechazo conocido del ledger: el diálogo sigue abierto con el motivo en español.
            if (result?.success === false) {
                toast.error(result.error ?? ti('portfolio.editTransaction.toastError'));
                return;
            }
            setOpen(false);
            toast.success(ti('portfolio.editTransaction.toastSuccess'));
            router.refresh();
        } catch (error) {
            // Nunca tragar un redirect de Next (p. ej. sesión caducada): debe navegar.
            if (isNextRedirectError(error)) throw error;
            showErrorToast(error);
        } finally {
            setLoading(false);
        }
    };

    return (
        <Dialog open={open} onOpenChange={handleOpenChange}>
            <DialogTrigger asChild>
                <Button
                    variant="ghost"
                    size="icon"
                    className="text-blue-400 hover:text-blue-300 hover:bg-blue-950/20"
                    // Boton solo-icono: sin nombre accesible el boton es
                    // announces como "boton" y no se sabe que edita (WCAG 4.1.2).
                    aria-label={ti('portfolio.editTransaction.titleWithSymbol', { symbol: transaction.symbol })}
                >
                    <Pencil aria-hidden="true" className="h-4 w-4" />
                </Button>
            </DialogTrigger>
            {/* Sin autofoco al abrir: Radix enfoca el primer campo (Símbolo) y
                TickerSearchInput lanza una búsqueda con el ticker precargado,
                abriendo el desplegable encima de Moneda/Tipo/Cantidad/Precio,
                que son los campos que sí se editan. El foco queda en el diálogo
                y el primer Tab entra al formulario. */}
            <DialogContent
                className="bg-gray-900 border-gray-700 max-w-md max-h-[90dvh] overflow-y-auto"
                onOpenAutoFocus={(event) => event.preventDefault()}
            >
                <DialogHeader>
                    <DialogTitle className="text-gray-100">{ti('portfolio.editTransaction.title')}</DialogTitle>
                    <DialogDescription className="text-gray-400">
                        {ti('portfolio.editTransaction.description')}
                    </DialogDescription>
                </DialogHeader>
                <form onSubmit={handleSubmit} noValidate className="space-y-4">
                    <div className="space-y-2">
                        <Label htmlFor="symbol" className="text-gray-300">{ti('portfolio.editTransaction.symbolLabel')}</Label>
                        <TickerSearchInput
                            id="symbol"
                            value={formData.symbol}
                            onValueChange={(value) => setFormData({ ...formData, symbol: value.toUpperCase() })}
                            onSelect={(stock) => setFormData({ ...formData, symbol: stock.symbol })}
                            required
                            className="bg-gray-800 border-gray-700 text-gray-100"
                        />
                        {fieldErrors.symbol && (
                            <p role="alert" className="text-sm text-red-400">{fieldErrors.symbol}</p>
                        )}
                    </div>

                    <TransactionFormFields
                        formData={formData}
                        onPatch={(patch) => setFormData({ ...formData, ...patch })}
                        fieldErrors={fieldErrors}
                        currencyId="edit-currency"
                        feesId="edit-fees"
                        onCancel={() => setOpen(false)}
                        saveLabel={ti('portfolio.editTransaction.save')}
                        loading={loading}
                        busy
                    />
                </form>
            </DialogContent>
        </Dialog>
    );
}
