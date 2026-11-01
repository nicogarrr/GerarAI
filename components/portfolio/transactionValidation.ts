/**
 * Validación pura del formulario "Nueva inversión" (cartera).
 *
 * Regla de oro: ningún submit puede fallar en silencio. Esta función se
 * ejecuta en cliente ANTES de llamar a la server action y devuelve un
 * mensaje por campo; la UI los pinta bajo cada input. Sin símbolo, cantidad
 * o precio válidos no hay petición al backend.
 */

import { todayLocal } from '@/lib/format';
import { parseLocalizedNumberDetailed } from '@/lib/i18n/parse-number';
import type { TranslateFn as TFunction } from '@/lib/i18n/translate';
import type { TranslationKey } from '@/lib/i18n/t';

/** Copias ES por defecto (byte-idénticas a las del diccionario
 *  lib/i18n/messages/es/portfolio.json#transactionForm, lo verifica el
 *  guard scripts/transaction-validation.test.ts): este módulo se importa
 *  también desde guards de node, que no cargan el registro de mensajes. */
export const TRANSACTION_VALIDATION_ES = {
  errSymbol: 'Busca y selecciona una acción de la lista.',
  errQuantity: 'Introduce una cantidad mayor que 0.',
  errPrice: 'Introduce un precio válido (0 o mayor).',
  errFees: 'Introduce una comisión válida (0 o mayor) o déjala vacía.',
  errDateInvalid: 'Fecha no válida (usa el selector de fecha).',
  errDateFuture: 'La fecha no puede ser futura.',
  errAmbiguous: 'Formato de número ambiguo: usa la coma para los decimales y el punto para los miles (ej. 1.234,56).',
} as const;

type ValidationMessageKey = keyof typeof TRANSACTION_VALIDATION_ES;

const VALIDATION_I18N_KEYS: Record<ValidationMessageKey, TranslationKey> = {
  errSymbol: 'portfolio.transactionForm.errSymbol',
  errQuantity: 'portfolio.transactionForm.errQuantity',
  errPrice: 'portfolio.transactionForm.errPrice',
  errFees: 'portfolio.transactionForm.errFees',
  errDateInvalid: 'portfolio.transactionForm.errDateInvalid',
  errDateFuture: 'portfolio.transactionForm.errDateFuture',
  errAmbiguous: 'portfolio.transactionForm.errAmbiguous',
};

export interface TransactionValidationOptions {
  /** Traductor del locale activo; sin él, copias ES por defecto. */
  ti?: TFunction;
  /** Locale para interpretar los números introducidos. */
  locale?: string;
}

export interface TransactionFormValues {
  symbol: string;
  type: 'buy' | 'sell';
  quantity: string;
  price: string;
  date: string;
  /** Comisión opcional (vacío = sin comisión). */
  fees?: string;
}

export interface TransactionFormErrors {
  symbol?: string;
  quantity?: string;
  price?: string;
  date?: string;
  fees?: string;
}

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

export function validateTransactionForm(values: TransactionFormValues, now: Date = new Date(), options: TransactionValidationOptions = {}): TransactionFormErrors {
  const { ti, locale = 'es' } = options;
  const msg = (key: ValidationMessageKey): string => (ti ? ti(VALIDATION_I18N_KEYS[key]) : TRANSACTION_VALIDATION_ES[key]);
  const errors: TransactionFormErrors = {};

  if (!values.symbol || !values.symbol.trim()) {
    errors.symbol = msg('errSymbol');
  }

  const quantity = parseLocalizedNumberDetailed(values.quantity, locale);
  if (!quantity.ok) {
    errors.quantity = quantity.error === 'ambiguous' ? msg('errAmbiguous') : msg('errQuantity');
  } else if (quantity.value <= 0) {
    errors.quantity = msg('errQuantity');
  }

  const price = parseLocalizedNumberDetailed(values.price, locale);
  if (!price.ok) {
    errors.price = price.error === 'ambiguous' ? msg('errAmbiguous') : msg('errPrice');
  } else if (price.value < 0) {
    errors.price = msg('errPrice');
  }

  if (values.fees !== undefined && values.fees.trim() !== '') {
    const fees = parseLocalizedNumberDetailed(values.fees, locale);
    if (!fees.ok) {
      errors.fees = fees.error === 'ambiguous' ? msg('errAmbiguous') : msg('errFees');
    } else if (fees.value < 0) {
      errors.fees = msg('errFees');
    }
  }

  if (!DATE_RE.test(values.date)) {
    errors.date = msg('errDateInvalid');
  } else {
    const day = new Date(`${values.date}T00:00:00`);
    if (Number.isNaN(day.getTime())) {
      errors.date = msg('errDateInvalid');
    } else {
      // Comparación por día de calendario (no por hora): mañana ya es futuro.
      // «Hoy» en USER_TZ, la misma base con la que el diálogo siembra la
      // fecha (todayLocal): con los getters locales del proceso, un proceso
      // una hora atrás (CI en UTC a las 23:xx, navegador al oeste de Madrid)
      // veía «ayer» y rechazaba la fecha sembrada como futura.
      const today = todayLocal(now);
      if (values.date > today) {
        errors.date = msg('errDateFuture');
      }
    }
  }

  return errors;
}

export function hasTransactionErrors(errors: TransactionFormErrors): boolean {
  return Object.keys(errors).length > 0;
}
