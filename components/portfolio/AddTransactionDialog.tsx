'use client';

import { useState } from 'react';
import {
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Button } from '@/components/ui/button';
import { TrendingUp } from 'lucide-react';
import { addTransaction } from '@/lib/actions/portfolio.actions';
import { TickerSearchInput } from '@/components/search/TickerSearchInput';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import { showErrorToast } from '@/lib/toast';
import { hasTransactionErrors, validateTransactionForm, type TransactionFormErrors } from './transactionValidation';
import { parseLocalizedNumber, todayLocal } from '@/lib/format';
import { currencyForTicker, currencyOptions, NEW_TRANSACTION_CURRENCY } from './transactionCurrencies';
import { SYMBOL_VALIDATION } from '@/lib/constants';

type DialogProps = {
  userId: string;
  onClose: () => void;
  /** Símbolo ya elegido al abrir (enlace «Registrar compra o venta» de la ficha). */
  initialSymbol?: string | null;
};

function validSymbol(raw: string | null | undefined): string | null {
  const symbol = (raw ?? '').trim().toUpperCase();
  return symbol.length >= SYMBOL_VALIDATION.MIN_LENGTH &&
    symbol.length <= SYMBOL_VALIDATION.MAX_LENGTH &&
    SYMBOL_VALIDATION.PATTERN.test(symbol)
    ? symbol
    : null;
}

export default function AddTransactionDialog({ userId, onClose, initialSymbol }: DialogProps) {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  // Un símbolo de la URL con forma inválida se ignora (formulario vacío).
  const [presetSymbol] = useState(() => validSymbol(initialSymbol));
  const [searchQuery, setSearchQuery] = useState(presetSymbol ?? '');
  // true cuando el usuario eligio la divisa a mano: entonces cambiar de ticker no la toca.
  const [currencyChosen, setCurrencyChosen] = useState(false);

  const [formData, setFormData] = useState({
    symbol: presetSymbol ?? '',
    companyName: '',
    type: 'buy' as 'buy' | 'sell',
    currency: presetSymbol ? currencyForTicker(presetSymbol) : NEW_TRANSACTION_CURRENCY,
    quantity: '',
    price: '',
    fees: '',
    date: todayLocal(),
    notes: '',
  });



  const [fieldErrors, setFieldErrors] = useState<TransactionFormErrors>({});

  // Alta por símbolo: si el buscador no encuentra la empresa (proveedor caído
  // o sin cuota, ticker poco común, mercado no cubierto) el diálogo era un
  // callejón sin salida, porque el símbolo solo se fijaba eligiendo una
  // sugerencia. Igual que en la watchlist: el texto con forma de ticker se
  // puede usar tal cual.
  const manualSymbol = searchQuery.trim().toUpperCase();
  const canUseManualSymbol = !formData.symbol && validSymbol(manualSymbol) !== null;

  const selectSymbol = (symbol: string, companyName: string) => {
    setFormData((prev) => ({
      ...prev,
      symbol,
      companyName,
      // La divisa sigue al ticker (SAN.MC -> EUR, luego AAPL -> USD) salvo
      // que el usuario la haya elegido a mano: esa eleccion se respeta.
      currency: currencyChosen ? prev.currency : currencyForTicker(symbol),
    }));
    setSearchQuery(symbol);
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
      const result = await addTransaction(
        userId,
        formData.symbol,
        formData.type,
        parseLocalizedNumber(formData.quantity) ?? 0,
        parseLocalizedNumber(formData.price) ?? 0,
        new Date(formData.date),
        formData.notes || undefined,
        formData.currency,
        parseLocalizedNumber(formData.fees) ?? 0,
      );
      // Rechazo conocido del ledger (vender más de lo que tienes, divisa distinta):
      // el formulario sigue abierto con lo escrito y el motivo en español.
      if (result?.success === false) {
        toast.error(result.error ?? 'No se pudo registrar la transacción.');
        return;
      }
      onClose();
      setFormData({
        symbol: '',
        companyName: '',
        type: 'buy',
        currency: NEW_TRANSACTION_CURRENCY,
        quantity: '',
        price: '',
        fees: '',
        date: todayLocal(),
        notes: '',
      });
      setSearchQuery('');
      setCurrencyChosen(false);
      toast.success('Transacción registrada');
      router.refresh();
    } catch (error) {
      // Nunca tragar un redirect de Next (p. ej. sesión caducada): debe navegar.
      const digest = (error as { digest?: unknown })?.digest;
      if (typeof digest === 'string' && digest.startsWith('NEXT_REDIRECT')) throw error;
      showErrorToast(error);
    } finally {
      setLoading(false);
    }
  };

  return (
      <DialogContent className="bg-gray-900 border-gray-700 max-w-md">
        <DialogHeader>
          <DialogTitle className="text-gray-100">Nueva Inversión</DialogTitle>
          <DialogDescription className="text-gray-400">
            Registra una compra o venta de acciones
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} noValidate className="space-y-4">
          {/* Buscador con autocompletado: el componente compartido de la app
              (misma búsqueda del buscador global, gate F215 y debounce). */}
          <div className="space-y-2">
            <Label htmlFor="symbol" className="text-gray-300">Buscar Acción</Label>
            <TickerSearchInput
              id="symbol"
              placeholder="Buscar por nombre o símbolo (ej: Apple, AAPL)"
              value={searchQuery}
              onValueChange={(value) => {
                setSearchQuery(value);
                if (value !== formData.symbol) {
                  setFormData({ ...formData, symbol: '', companyName: '' });
                }
              }}
              onSelect={(stock) => selectSymbol(stock.symbol, stock.name)}
              className="bg-gray-800 border-gray-700 text-gray-100 w-full"
            />
            {canUseManualSymbol && (
              <div className="flex flex-wrap items-center gap-2 text-sm text-gray-400">
                <span>¿No aparece en la lista?</span>
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => selectSymbol(manualSymbol, '')}
                  className="min-h-[44px] px-2 text-teal-300 hover:bg-teal-950/40 hover:text-teal-200"
                >
                  Usar «{manualSymbol}» como símbolo
                </Button>
              </div>
            )}
            {fieldErrors.symbol && (
              <p role="alert" className="text-sm text-red-400">{fieldErrors.symbol}</p>
            )}

            {/* Acción seleccionada */}
            {formData.symbol && (
              <div className="flex items-center gap-2 p-2 bg-teal-900/30 rounded border border-teal-700">
                <TrendingUp className="h-4 w-4 text-teal-400" />
                <span className="text-teal-300 font-medium">{formData.symbol}</span>
                {formData.companyName ? (
                  <span className="text-gray-400 text-sm">- {formData.companyName}</span>
                ) : null}
              </div>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="currency" className="text-gray-300">Moneda de la operación</Label>
            <Select value={formData.currency} onValueChange={(currency) => { setCurrencyChosen(true); setFormData({ ...formData, currency }); }}>
              <SelectTrigger id="currency" className="bg-gray-800 border-gray-700 text-gray-100"><SelectValue /></SelectTrigger>
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
                placeholder="10"
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
                placeholder="150,00"
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
            <Label htmlFor="fees" className="text-gray-300">Comisiones ({formData.currency}) (opcional)</Label>
            <Input
              id="fees"
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
              placeholder="Notas sobre la transacción"
              value={formData.notes}
              onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
              className="bg-gray-800 border-gray-700 text-gray-100"
            />
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="outline" onClick={() => onClose()}>
              Cancelar
            </Button>
            <Button
              type="submit"
              disabled={loading}
            >
              {loading ? 'Guardando...' : 'Guardar Inversión'}
            </Button>
          </div>
        </form>
      </DialogContent>
  );
}
