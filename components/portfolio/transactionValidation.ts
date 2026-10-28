/**
 * Validación pura del formulario "Nueva Inversión" (cartera).
 *
 * Regla de oro: ningún submit puede fallar en silencio. Esta función se
 * ejecuta en cliente ANTES de llamar a la server action y devuelve un
 * mensaje por campo; la UI los pinta bajo cada input. Sin símbolo, cantidad
 * o precio válidos no hay petición al backend.
 */

import { parseLocalizedNumberDetailed } from '@/lib/format';

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

/**
 * El parser rechaza los formatos ambiguos («1,234.5», «1,234») en lugar de
 * reinterpretarlos con un factor 1000 silencioso; este mensaje enseña el
 * formato esperado en vez de acusar al usuario de escribir «mal» el número.
 */
const AMBIGUOUS_NUMBER_MESSAGE =
  'Formato de número ambiguo: usa la coma para los decimales y el punto para los miles (ej. 1.234,56).';

export function validateTransactionForm(values: TransactionFormValues, now: Date = new Date()): TransactionFormErrors {
  const errors: TransactionFormErrors = {};

  if (!values.symbol || !values.symbol.trim()) {
    errors.symbol = 'Busca y selecciona una acción de la lista.';
  }

  const quantity = parseLocalizedNumberDetailed(values.quantity);
  if (!quantity.ok) {
    errors.quantity = quantity.error === 'ambiguous' ? AMBIGUOUS_NUMBER_MESSAGE : 'Introduce una cantidad mayor que 0.';
  } else if (quantity.value <= 0) {
    errors.quantity = 'Introduce una cantidad mayor que 0.';
  }

  const price = parseLocalizedNumberDetailed(values.price);
  if (!price.ok) {
    errors.price = price.error === 'ambiguous' ? AMBIGUOUS_NUMBER_MESSAGE : 'Introduce un precio válido (0 o mayor).';
  } else if (price.value < 0) {
    errors.price = 'Introduce un precio válido (0 o mayor).';
  }

  if (values.fees !== undefined && values.fees.trim() !== '') {
    const fees = parseLocalizedNumberDetailed(values.fees);
    if (!fees.ok) {
      errors.fees = fees.error === 'ambiguous' ? AMBIGUOUS_NUMBER_MESSAGE : 'Introduce una comisión válida (0 o mayor) o déjala vacía.';
    } else if (fees.value < 0) {
      errors.fees = 'Introduce una comisión válida (0 o mayor) o déjala vacía.';
    }
  }

  if (!DATE_RE.test(values.date)) {
    errors.date = 'Fecha no válida (usa el selector de fecha).';
  } else {
    const day = new Date(`${values.date}T00:00:00`);
    if (Number.isNaN(day.getTime())) {
      errors.date = 'Fecha no válida (usa el selector de fecha).';
    } else {
      // Comparación por día de calendario (no por hora): mañana ya es futuro.
      const pad = (n: number) => String(n).padStart(2, '0');
      const today = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
      if (values.date > today) {
        errors.date = 'La fecha no puede ser futura.';
      }
    }
  }

  return errors;
}

export function hasTransactionErrors(errors: TransactionFormErrors): boolean {
  return Object.keys(errors).length > 0;
}
