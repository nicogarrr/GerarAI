'use client';

import { useState } from 'react';
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
import { TickerSearchInput } from '@/components/search/TickerSearchInput';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Pencil } from 'lucide-react';
import { updateTransaction } from '@/lib/actions/portfolio.actions';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import { showErrorToast } from '@/lib/toast';
import { currencyOptions } from './transactionCurrencies';
import { hasTransactionErrors, validateTransactionForm, type TransactionFormErrors } from './transactionValidation';
import { formatNumberForInput, parseLocalizedNumber } from '@/lib/format';

type Transaction = {
    _id: string;
    symbol: string;
    type: 'buy' | 'sell';
    quantity: number;
    price: number;
    fees?: number;
    date: string;
    notes?: string;
    currency?: string;
};

type Props = {
    transaction: Transaction;
    userId: string;
};

function initialForm(transaction: Transaction) {
    return {
        symbol: transaction.symbol,
        type: transaction.type,
        quantity: formatNumberForInput(transaction.quantity),
        price: formatNumberForInput(transaction.price),
        // Sin dato de comisión en la fila el campo queda vacío: guardar sin tocarlo OMITE fees y el backend conserva la registrada (nunca se resetea a 0).
        fees: transaction.fees === undefined ? '' : formatNumberForInput(transaction.fees),
        date: transaction.date.slice(0, 10),
        notes: transaction.notes || '',
        // La divisa guardada se conserva aunque no esté en la lista corta
        // (SEK, DKK, NOK… de IBKR): antes el selector salía en blanco.
        currency: transaction.currency || 'USD',
    };
}

export default function EditTransactionDialog({ transaction, userId }: Props) {
    const router = useRouter();
    const [open, setOpen] = useState(false);
    const [loading, setLoading] = useState(false);
    const [fieldErrors, setFieldErrors] = useState<TransactionFormErrors>({});

    const [formData, setFormData] = useState(() => initialForm(transaction));
    // Cada apertura parte de lo guardado: antes, cancelar tras tocar campos
    // dejaba esos cambios sin guardar en el formulario y al reabrirlo parecían
    // los datos reales del movimiento.
    const handleOpenChange = (next: boolean) => {
        if (next) {
            setFormData(initialForm(transaction));
            setFieldErrors({});
        }
        setOpen(next);
    };

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        const errors = validateTransactionForm({
            symbol: formData.symbol,
            type: formData.type,
            quantity: formData.quantity,
            price: formData.price,
            fees: formData.fees,
            date: formData.date,
        });
        setFieldErrors(errors);
        if (hasTransactionErrors(errors)) return;
        setLoading(true);

        try {
            await updateTransaction(
                userId,
                transaction._id,
                formData.symbol,
                formData.type,
                parseLocalizedNumber(formData.quantity) ?? 0,
                parseLocalizedNumber(formData.price) ?? 0,
                new Date(formData.date),
                formData.notes || undefined,
                formData.currency,
                // Sin dato de comisión en la fila no se envía (el backend conserva la registrada).
                transaction.fees === undefined && formData.fees.trim() === ''
                    ? undefined
                    : (parseLocalizedNumber(formData.fees) ?? 0),
            );
            setOpen(false);
            toast.success('Transacción actualizada');
            router.refresh();
        } catch (error) {
            const digest = (error as { digest?: unknown })?.digest;
            if (typeof digest === 'string' && digest.startsWith('NEXT_REDIRECT')) throw error;
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
                    aria-label={`Editar transacción de ${transaction.symbol}`}
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
                className="bg-gray-900 border-gray-700 max-w-md"
                onOpenAutoFocus={(event) => event.preventDefault()}
            >
                <DialogHeader>
                    <DialogTitle className="text-gray-100">Editar Transacción</DialogTitle>
                    <DialogDescription className="text-gray-400">
                        Modifica los detalles de la transacción
                    </DialogDescription>
                </DialogHeader>
                <form onSubmit={handleSubmit} noValidate className="space-y-4">
                    <div className="space-y-2">
                        <Label htmlFor="symbol" className="text-gray-300">Símbolo</Label>
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

                    <div className="space-y-2">
                        <Label htmlFor="edit-currency" className="text-gray-300">Moneda de la operación</Label>
                        <Select value={formData.currency} onValueChange={(currency) => setFormData({ ...formData, currency })}>
                            <SelectTrigger id="edit-currency" className="bg-gray-800 border-gray-700 text-gray-100"><SelectValue /></SelectTrigger>
                            <SelectContent className="bg-gray-800 border-gray-700">
                                {currencyOptions(formData.currency).map((currency) => <SelectItem value={currency} key={currency}>{currency}</SelectItem>)}
                            </SelectContent>
                        </Select>
                    </div>

                    <div className="space-y-2">
                        <Label htmlFor="type" className="text-gray-300">Tipo de Operación</Label>
                        <Select
                            value={formData.type}
                            onValueChange={(value: 'buy' | 'sell') => setFormData({ ...formData, type: value })}
                        >
                            <SelectTrigger className="bg-gray-800 border-gray-700 text-gray-100">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent className="bg-gray-800 border-gray-700">
                                <SelectItem value="buy">🟢 Compra</SelectItem>
                                <SelectItem value="sell">🔴 Venta</SelectItem>
                            </SelectContent>
                        </Select>
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                        <div className="space-y-2">
                            <Label htmlFor="quantity" className="text-gray-300">Cantidad</Label>
                            <Input
                                id="quantity"
                                type="text"
                                inputMode="decimal"
                                value={formData.quantity}
                                onChange={(e) => setFormData({ ...formData, quantity: e.target.value })}
                                required
                                className="bg-gray-800 border-gray-700 text-gray-100"
                            />
                            {fieldErrors.quantity && (
                                <p role="alert" className="text-sm text-red-400">{fieldErrors.quantity}</p>
                            )}
                        </div>

                        <div className="space-y-2">
                            <Label htmlFor="price" className="text-gray-300">Precio ({formData.currency})</Label>
                            <Input
                                id="price"
                                type="text"
                                inputMode="decimal"
                                value={formData.price}
                                onChange={(e) => setFormData({ ...formData, price: e.target.value })}
                                required
                                className="bg-gray-800 border-gray-700 text-gray-100"
                            />
                            {fieldErrors.price && (
                                <p role="alert" className="text-sm text-red-400">{fieldErrors.price}</p>
                            )}
                        </div>
                    </div>

                    <div className="space-y-2">
                      <Label htmlFor="edit-fees" className="text-gray-300">Comisiones ({formData.currency}) (opcional)</Label>
                      <Input
                        id="edit-fees"
                        type="text"
                                inputMode="decimal"
                        placeholder="0,00"
                        value={formData.fees}
                        onChange={(e) => setFormData({ ...formData, fees: e.target.value })}
                        className="bg-gray-800 border-gray-700 text-gray-100"
                      />
                      {fieldErrors.fees && (
                        <p role="alert" className="text-sm text-red-400">{fieldErrors.fees}</p>
                      )}
                    </div>

                    <div className="space-y-2">
                        <Label htmlFor="date" className="text-gray-300">Fecha</Label>
                        <Input
                            id="date"
                            type="date"
                            value={formData.date}
                            onChange={(e) => setFormData({ ...formData, date: e.target.value })}
                            required
                            className="bg-gray-800 border-gray-700 text-gray-100"
                        />
                        {fieldErrors.date && (
                            <p role="alert" className="text-sm text-red-400">{fieldErrors.date}</p>
                        )}
                    </div>

                    <div className="space-y-2">
                        <Label htmlFor="notes" className="text-gray-300">Notas (opcional)</Label>
                        <Input
                            id="notes"
                            value={formData.notes}
                            onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
                            className="bg-gray-800 border-gray-700 text-gray-100"
                        />
                    </div>

                    <div className="flex justify-end gap-2 pt-2">
                        <Button type="button" variant="outline" onClick={() => setOpen(false)}>
                            Cancelar
                        </Button>
                        <Button
                            type="submit"
                            disabled={loading}
                            aria-busy={loading}
                        >
                            {loading ? 'Guardando...' : 'Guardar Cambios'}
                        </Button>
                    </div>
                </form>
            </DialogContent>
        </Dialog>
    );
}
