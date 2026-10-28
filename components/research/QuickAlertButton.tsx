'use client';

import { useState, useSyncExternalStore } from 'react';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { BellPlus, Loader2 } from 'lucide-react';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { createAlertResult, type AlertType } from '@/lib/actions/alerts.actions';
import { toast } from 'sonner';
import { showErrorToast } from '@/lib/toast';
import { formatMoney, parseLocalizedNumber } from '@/lib/format';

const subscribeHydration = () => () => undefined;

const ALERT_TYPES: Array<{ value: AlertType; label: string; needsValue: boolean; valuePlaceholder: string }> = [
  { value: 'price_above', label: 'Precio por encima de', needsValue: true, valuePlaceholder: 'Precio objetivo' },
  { value: 'price_below', label: 'Precio por debajo de', needsValue: true, valuePlaceholder: 'Precio objetivo' },
  { value: 'price_change', label: 'Cambio de precio %', needsValue: true, valuePlaceholder: 'Variación objetivo %' },
  { value: 'news', label: 'Nueva noticia', needsValue: false, valuePlaceholder: '' },
  { value: 'earnings', label: 'Reporte de ganancias', needsValue: false, valuePlaceholder: '' },
];

// Símbolo visible junto al precio objetivo: la alerta es sobre el precio
// del mercado del valor, así que la divisa es la de su bolsa, no siempre $.
const CURRENCY_SYMBOL: Record<string, string> = {
  EUR: '€',
  // '$' para USD: es lo habitual en es-ES y coincide con los tests E2E existentes.
  USD: '$',
  GBP: '£',
  GBX: 'p',
  JPY: '¥',
  CHF: 'CHF ',
  SEK: 'kr ',
  DKK: 'kr ',
  NOK: 'kr ',
  HKD: 'HK$',
  MXN: 'MX$',
  BRL: 'R$',
  CAD: 'CA$',
  AUD: 'A$',
};

/**
 * Alerta rápida desde la ficha de research: selector de tipo de alerta y,
 * opcionalmente, deep-link a /alerts con el diálogo de creación
 * pre-rellenado para tipos más complejos.
 */
export default function QuickAlertButton({ ticker, currency = 'USD', compact = false }: { ticker: string; currency?: string; compact?: boolean }) {
  const hydrated = useSyncExternalStore(subscribeHydration, () => true, () => false);
  const symbol = CURRENCY_SYMBOL[currency] ?? `${currency} `;
  const [type, setType] = useState<AlertType>('price_above');
  const [price, setPrice] = useState('');
  const [busy, setBusy] = useState(false);

  const meta = ALERT_TYPES.find((item) => item.value === type) ?? ALERT_TYPES[0];
  const numericValue = parseLocalizedNumber(price);

  const onCreate = async () => {
    let value: number | string = '';
    if (meta.needsValue) {
      if (numericValue === null || !Number.isFinite(numericValue) || numericValue <= 0) {
        toast.error(
          type === 'price_change'
            ? 'Introduce una variación objetivo válida'
            : 'Introduce un precio objetivo válido',
        );
        return;
      }
      value = numericValue;
    }
    setBusy(true);
    try {
      const result = await createAlertResult({
        symbol: ticker,
        type,
        condition: {
          operator: type === 'price_below' ? '<' : '>',
          value,
        },
      });
      if (!result.ok) {
        // Rechazo de negocio (símbolo no reconocido, duplicada): su mensaje,
        // nunca «motor caído, reintenta» (ver createAlertResult).
        if (result.cause === 'duplicate') toast.info(result.message);
        else toast.error(result.message);
        return;
      }
      toast.success(
        meta.needsValue
          ? `Alerta creada: ${ticker} ${meta.label.toLowerCase()} ${type === 'price_change' ? `${value}%` : formatMoney(value, currency)}`
          : `Alerta creada: ${ticker} · ${meta.label}`,
      );
      setPrice('');
    } catch (error) {
      showErrorToast(error, {
        duplicateMessage: 'Ya tienes esta alerta configurada.',
        onRetry: onCreate,
      });
    } finally {
      setBusy(false);
    }
  };

  // Botón campana compacto alineado con los enlaces de la ficha; el formulario
  // vive en un popover para no descolocar la fila. "Ver alertas" abre /alerts
  // (href exacto que espera el e2e) para tipos avanzados o edición.
  const deepLink = '/alerts';

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button size="sm" variant={compact ? 'ghost' : 'outline'} aria-label="Alerta de precio" className={compact ? 'size-11 gap-1.5 p-0 text-gray-300 hover:text-teal-300 sm:h-8 sm:w-auto sm:px-3 sm:text-xs' : 'min-h-[44px] gap-1.5 px-3 text-sm sm:min-h-0 sm:h-8 sm:text-xs'}>
          <BellPlus aria-hidden="true" className="h-4 w-4 sm:h-3.5 sm:w-3.5" />
          {compact ? <span className="hidden sm:inline">Alerta de precio</span> : 'Alerta de precio'}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80 border-gray-700 bg-gray-900">
        <div className="flex flex-col gap-3">
          <Select value={type} onValueChange={(value: AlertType) => setType(value)}>
            <SelectTrigger
              aria-label="Tipo de alerta"
              className="h-11 w-full bg-surface-1 text-base sm:h-9 sm:text-sm"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-gray-900 border-gray-600">
              {ALERT_TYPES.map((item) => (
                <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          {meta.needsValue ? (
            <Input
              value={price}
              onChange={(e) => setPrice(e.target.value)}
              // type="text" (no "number"): Chrome rechaza la coma decimal en
              // inputs numéricos y parseLocalizedNumber ya tolera "8,5" es-ES.
              type="text"
              inputMode="decimal"
              placeholder={meta.needsValue && type !== 'price_change' ? `${meta.valuePlaceholder} ${symbol}` : meta.valuePlaceholder}
              aria-label={type === 'price_change' ? 'Variación objetivo en porcentaje' : `Precio objetivo en ${currency}`}
              className="h-11 w-full bg-surface-1 text-base sm:h-9 sm:text-sm"
            />
          ) : null}
          <div className="flex items-center gap-2">
            <Button size="sm" variant="outline" onClick={onCreate} disabled={busy || !hydrated} aria-busy={busy} className="min-h-[44px] flex-1 gap-1.5 px-4 text-sm sm:min-h-0 sm:h-9">
              {busy ? <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" /> : <BellPlus aria-hidden="true" className="h-4 w-4" />}
              + Alerta
            </Button>
            <Button size="sm" variant="ghost" asChild className="min-h-[44px] px-4 text-sm text-gray-300 sm:min-h-0 sm:h-9">
              <Link href={deepLink}>Ver alertas</Link>
            </Button>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}
