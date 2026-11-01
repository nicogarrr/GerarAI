/**
 * Lógica de presentación de la proyección de dividendos, separada del JSX
 * para poder canary-testearla (patrón lib/portfolio-score-display.ts).
 *
 * Regla de veracidad: los null del backend se propagan como null (la vista
 * los pinta N/D); las notas de veracidad del payload nunca se descartan.
 */
// @ts-expect-error TS5097
import { createTranslator } from './i18n/translate.ts';
import type {
  DividendProjectionDeclaredFuture,
  DividendProjectionFiscalYear,
} from '@/lib/actions/portfolio.actions';

export type DeclaredFutureNoteView = {
  /** Nota única compartida por todas las entradas (null si difieren o no hay). */
  sharedNote: string | null;
  /** Nota por entrada solo cuando no hay nota compartida. */
  perItemNotes: Array<string | null>;
  /** Fecha de corte común de las entradas (null si difieren o no hay). */
  sharedAsOf: string | null;
};

/**
 * La nota del backend ("según el proveedor de datos, no verificado contra
 * fuente primaria; no alimenta la réplica") es una salvedad de veracidad:
 * INGESTADO desde el proveedor NO equivale a confirmación corporativa, así
 * que la nota siempre llega a la pantalla. Si todas las entradas traen la
 * misma nota se muestra una vez como descripción del panel; si difieren, va
 * en cada línea (perItemNotes).
 */
export function declaredFutureNoteView(
  items: DividendProjectionDeclaredFuture[],
): DeclaredFutureNoteView {
  const notes = [...new Set(items.map((item) => item.note).filter((note) => note.length > 0))];
  const asOfs = [...new Set(items.map((item) => item.projection_as_of).filter((v) => v.length > 0))];
  const sharedNote = notes.length === 1 ? notes[0] : null;
  return {
    sharedNote,
    perItemNotes: items.map((item) => (sharedNote === null && item.note.length > 0 ? item.note : null)),
    sharedAsOf: asOfs.length === 1 ? asOfs[0] : null,
  };
}

export type FiscalCardRow = {
  label: string;
  /** Importe en divisa base; null = N/D (ausente), nunca 0. */
  value: number | null;
};

/**
 * Filas de la tarjeta de escenario fiscal de un año. Los campos que el
 * backend deja en null (base no EUR, año sin cobertura...) se devuelven como
 * null para que la tarjeta pinte N/D y la nota del año lo explique.
 */
export function fiscalCardRows(data: DividendProjectionFiscalYear, locale: 'es' | 'en' = 'es'): FiscalCardRow[] {
  const t = createTranslator(locale);
  return [
    { label: t('portfolio.dividendFiscal.gross'), value: data.gross_base },
    { label: t('portfolio.dividendFiscal.sourceWithheld'), value: data.source_withheld_foreign },
    { label: t('portfolio.dividendFiscal.doubleTaxRelief'), value: data.double_tax_deduction },
    { label: t('portfolio.dividendFiscal.spanishWithholding'), value: data.retencion_a_cuenta_es },
    { label: t('portfolio.dividendFiscal.irpfScenario'), value: data.irpf_scenario },
    { label: t('portfolio.dividendFiscal.taxDue'), value: data.cuota_pendiente_estimada },
    { label: t('portfolio.dividendFiscal.netScenario'), value: data.net_scenario },
  ];
}

/**
 * La nota del año explica los N/D (escenario no disponible por divisa base no
 * EUR, subconjunto cubierto con excluidas...). Nunca se descarta.
 */
export function fiscalYearNote(data: DividendProjectionFiscalYear): string | null {
  return data.note.length > 0 ? data.note : null;
}

/**
 * Cantidad de títulos con hasta 6 decimales (schema Numeric(20,6)): una
 * posición fraccionaria 0,000001 no puede pintarse como "0" (sería inventar
 * una ausencia). Los ceros de relleno a la derecha se recortan.
 */
export function formatPositionQuantity(quantity: number): string {
  return quantity.toLocaleString('es-ES', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 6,
  });
}
