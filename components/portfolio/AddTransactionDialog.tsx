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

// Divisa probable segun el sufijo de mercado del ticker (B5): al elegir
// SAN.MC la moneda no puede quedarse en USD por defecto. El usuario puede
// cambiarla despues; esto solo fija un default razonable.
const SUFFIX_CURRENCY: Record<string, string> = {
  MC: 'EUR', PA: 'EUR', AS: 'EUR', BR: 'EUR', LS: 'EUR', DE: 'EUR',
  F: 'EUR', MI: 'EUR', VI: 'EUR', HE: 'EUR', ST: 'EUR', CO: 'EUR',
  OL: 'EUR', AT: 'EUR', IR: 'EUR', DU: 'EUR', HM: 'EUR', MU: 'EUR',
  L: 'GBP', IL: 'GBP', SW: 'CHF', VX: 'CHF', TO: 'CAD', V: 'CAD',
  HK: 'HKD', T: 'JPY', AX: 'AUD', SS: 'CNY', SZ: 'CNY',
};

function defaultCurrencyFor(symbol: string): string | null {
  const idx = symbol.lastIndexOf('.');
  if (idx < 0) return null;
  return SUFFIX_CURRENCY[symbol.slice(idx + 1).toUpperCase()] ?? null;
}


type DialogProps = {
  userId: string;
  onClose: () => void;
  /** Alta desde una ficha concreta (p. ej. watchlist): la acción ya va
      seleccionada y el usuario solo añade cantidad, precio y fecha. */
  initialSymbol?: string;
  initialCompanyName?: string;
};

export default function AddTransactionDialog({ userId, onClose, initialSymbol, initialCompanyName }: DialogProps) {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState(initialSymbol ?? '');

  const [formData, setFormData] = useState({
    symbol: initialSymbol ?? '',
    companyName: initialCompanyName ?? '',
    type: 'buy' as 'buy' | 'sell',
    currency: (initialSymbol ? defaultCurrencyFor(initialSymbol) : null) ?? 'USD',
    quantity: '',
    price: '',
    fees: '',
    date: todayLocal(),
    notes: '',
  });



  const [fieldErrors, setFieldErrors] = useState<TransactionFormErrors>({});

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
      await addTransaction(
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
      onClose();
      setFormData({
        symbol: '',
        companyName: '',
        type: 'buy',
        currency: 'USD',
        quantity: '',
        price: '',
        fees: '',
        date: todayLocal(),
        notes: '',
      });
      setSearchQuery('');
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
              onSelect={(stock) => {
                setFormData((prev) => ({
                  ...prev,
                  symbol: stock.symbol,
                  companyName: stock.name,
                  // Solo se sobrescribe la divisa si el usuario aun tiene el default USD:
                  // una eleccion manual previa se respeta.
                  currency:
                    prev.currency === 'USD'
                      ? (defaultCurrencyFor(stock.symbol) ?? prev.currency)
                      : prev.currency,
                }));
                setSearchQuery(stock.symbol);
              }}
              className="bg-gray-800 border-gray-700 text-gray-100 w-full"
            />
            {fieldErrors.symbol && (
              <p role="alert" className="text-sm text-red-400">{fieldErrors.symbol}</p>
            )}

            {/* Acción seleccionada */}
            {formData.symbol && (
              <div className="flex items-center gap-2 p-2 bg-teal-900/30 rounded border border-teal-700">
                <TrendingUp className="h-4 w-4 text-teal-400" />
                <span className="text-teal-300 font-medium">{formData.symbol}</span>
                <span className="text-gray-400 text-sm">- {formData.companyName}</span>
              </div>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="currency" className="text-gray-300">Moneda de la operación</Label>
            <Select value={formData.currency} onValueChange={(currency) => setFormData({ ...formData, currency })}>
              <SelectTrigger id="currency" className="bg-gray-800 border-gray-700 text-gray-100"><SelectValue /></SelectTrigger>
              <SelectContent className="bg-gray-800 border-gray-700">
                {['USD', 'EUR', 'GBP', 'JPY', 'CNY', 'HKD', 'CHF', 'CAD', 'AUD'].map((currency) => <SelectItem value={currency} key={currency}>{currency}</SelectItem>)}
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
