'use client';

import { useState } from 'react';
import {
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { TrendingUp } from 'lucide-react';
import { addTransaction } from '@/lib/actions/portfolio.actions';
import { TickerSearchInput } from '@/components/search/TickerSearchInput';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import { showErrorToast } from '@/lib/toast';
import { isNextRedirectError } from '@/lib/types/errors';
import { hasTransactionErrors, validateTransactionForm, type TransactionFormErrors } from './transactionValidation';
import { TransactionFormFields } from './TransactionFormFields';
import { todayLocal } from '@/lib/format';
import { parseLocalizedNumber } from '@/lib/i18n/parse-number';
import { useLocale, useT } from '@/lib/i18n/client';
import { currencyForTicker, NEW_TRANSACTION_CURRENCY, presetTransactionCurrency } from './transactionCurrencies';
import { SYMBOL_VALIDATION } from '@/lib/constants';

type DialogProps = {
  userId: string;
  onClose: () => void;
  /** Símbolo ya elegido al abrir (enlace «Registrar compra o venta» de la ficha). */
  initialSymbol?: string | null;
  initialCompanyName?: string;
  /** Verified listing currency from the source view, never an inferred display amount. */
  initialCurrency?: string | null;
};

function validSymbol(raw: string | null | undefined): string | null {
  const symbol = (raw ?? '').trim().toUpperCase();
  return symbol.length >= SYMBOL_VALIDATION.MIN_LENGTH &&
    symbol.length <= SYMBOL_VALIDATION.MAX_LENGTH &&
    SYMBOL_VALIDATION.PATTERN.test(symbol)
    ? symbol
    : null;
}

export default function AddTransactionDialog({ userId, onClose, initialSymbol, initialCompanyName, initialCurrency }: DialogProps) {
  const ti = useT();
  const locale = useLocale();
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  // Un símbolo de la URL con forma inválida se ignora (formulario vacío).
  const [presetSymbol] = useState(() => validSymbol(initialSymbol));
  const [searchQuery, setSearchQuery] = useState(presetSymbol ?? '');
  // true cuando el usuario eligio la divisa a mano: entonces cambiar de ticker no la toca.
  const [currencyChosen, setCurrencyChosen] = useState(false);

  const [formData, setFormData] = useState({
    symbol: presetSymbol ?? '',
    companyName: presetSymbol ? initialCompanyName ?? '' : '',
    type: 'buy' as 'buy' | 'sell',
    currency: presetSymbol ? presetTransactionCurrency(presetSymbol, initialCurrency) : NEW_TRANSACTION_CURRENCY,
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
    const errors = validateTransactionForm(formData, new Date(), { ti, locale });
    setFieldErrors(errors);
    if (hasTransactionErrors(errors)) return;
    setLoading(true);

    try {
      const result = await addTransaction(
        userId,
        formData.symbol,
        formData.type,
        parseLocalizedNumber(formData.quantity, locale) ?? 0,
        parseLocalizedNumber(formData.price, locale) ?? 0,
        new Date(formData.date),
        formData.notes || undefined,
        formData.currency,
        parseLocalizedNumber(formData.fees, locale) ?? 0,
      );
      // Rechazo conocido del ledger (vender más de lo que tienes, divisa distinta):
      // el formulario sigue abierto con lo escrito y el motivo en español.
      if (result?.success === false) {
        toast.error(result.error ?? ti('portfolio.addTransaction.toastError'));
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
      toast.success(ti('portfolio.addTransaction.toastSuccess'));
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
      <DialogContent className="bg-gray-900 border-gray-700 max-w-md max-h-[90dvh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="text-gray-100">{ti('portfolio.addTransaction.title')}</DialogTitle>
          <DialogDescription className="text-gray-400">
            {ti('portfolio.addTransaction.description')}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} noValidate className="space-y-4">
          {/* Buscador con autocompletado: el componente compartido de la app
              (misma búsqueda del buscador global, gate F215 y debounce). */}
          <div className="space-y-2">
            <Label htmlFor="symbol" className="text-gray-300">{ti('portfolio.addTransaction.searchLabel')}</Label>
            <TickerSearchInput
              id="symbol"
              placeholder={ti('portfolio.addTransaction.searchPlaceholder')}
              value={searchQuery}
              onValueChange={(value) => {
                setSearchQuery(value);
                if (value !== formData.symbol) {
                  setFormData({ ...formData, symbol: '', companyName: '' });
                }
              }}
              initialSelectedValue={presetSymbol ?? undefined}
              onSelect={(stock) => selectSymbol(stock.symbol, stock.name)}
              className="bg-gray-800 border-gray-700 text-gray-100 w-full"
            />
            {canUseManualSymbol && (
              <div className="flex flex-wrap items-center gap-2 text-sm text-gray-400">
                <span>{ti('portfolio.addTransaction.notInList')}</span>
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => selectSymbol(manualSymbol, '')}
                  className="min-h-[44px] px-2 text-teal-300 hover:bg-teal-950/40 hover:text-teal-200"
                >
                  {ti('portfolio.addTransaction.useManual', { symbol: manualSymbol })}
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

          <TransactionFormFields
            formData={formData}
            onPatch={(patch) => setFormData({ ...formData, ...patch })}
            fieldErrors={fieldErrors}
            currencyId="currency"
            feesId="fees"
            onCurrencyChange={(currency) => { setCurrencyChosen(true); setFormData({ ...formData, currency }); }}
            quantityPlaceholder="10"
            pricePlaceholder={ti('portfolio.addTransaction.pricePlaceholder')}
            notesPlaceholder={ti('portfolio.addTransaction.notesPlaceholder')}
            onCancel={onClose}
            saveLabel={ti('portfolio.addTransaction.save')}
            loading={loading}
          />
        </form>
      </DialogContent>
  );
}
