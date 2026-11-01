import type { TranslateFn } from '@/lib/i18n/translate';

export type ImageRow = { raw: string; identity: string; quantity: string | null; currency: string | null; warning: string };
export type ConfirmedImageRow = { ticker: string; quantity: string; currency: string; confirmed: boolean };
export type ImagePreview = { image_hash: string; rows: ImageRow[]; message: string };
export type ImageInstrument = { ticker: string; name: string; exchange: string; currency: string };
/**
 * Resultado de las server actions de importación por imagen. En producción Next
 * oculta el mensaje de cualquier error lanzado desde una server action, así que
 * los motivos en español del backend («Usa una imagen PNG, JPEG o WebP…»,
 * «Cotización caducada. Vuelve a revisar») se devuelven como dato.
 */
export type ImageActionResult<T> = { ok: true; data: T } | { ok: false; error: string };

export function unwrapImageResult<T>(result: ImageActionResult<T>): T {
    if (result.ok) return result.data;
    throw new Error(result.error);
}

export type ImageReview = { review_id: number; can_confirm: boolean; base_currency: string; already_imported: boolean; rows: Array<ConfirmedImageRow & { name: string; exchange: string; price: string | null; timestamp: number | null; source: string; value_native: string | null; value_base: string | null; weight_percent: string | null }> };

export function imageFileError(file: Pick<File, 'size' | 'type'>, t: TranslateFn): string | null {
    if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) return t('portfolio.importImage.fileType');
    if (file.size === 0 || file.size > 2 * 1024 * 1024) return t('portfolio.importImage.fileSize');
    return null;
}

/**
 * Cantidad escrita a mano en la revisión: admite decimal con coma (12,5) o
 * punto (12.5) y devuelve la forma que acepta el backend (12.5). Antes solo
 * valía el punto y «12,5» dejaba el botón deshabilitado sin decir por qué.
 * Separadores de miles no: «1.250» se lee como 1,25 (y la vista lo muestra).
 */
export function normalizeImageQuantity(input: string): string | null {
    const value = input.trim();
    const normalized = /^\d+,\d{1,6}$/.test(value) ? value.replace(',', '.') : value;
    if (!/^\d+(?:\.\d{1,6})?$/.test(normalized) || !(Number(normalized) > 0)) return null;
    return normalized;
}

/** Qué falta para poder consultar precios, o null si está todo listo. */
export function imageRowsPending(rows: Array<{ instrument: unknown; checked: boolean; quantity: string }>, t: TranslateFn): string | null {
    if (rows.length === 0) return t('portfolio.importImage.pendingNoRows');
    const missing: string[] = [];
    const noInstrument = rows.filter(row => !row.instrument).length;
    const badQuantity = rows.filter(row => normalizeImageQuantity(row.quantity) === null).length;
    const unchecked = rows.filter(row => row.instrument && !row.checked).length;
    if (noInstrument) missing.push(t(noInstrument === 1 ? 'portfolio.importImage.pendingNoInstrumentOne' : 'portfolio.importImage.pendingNoInstrumentMany', { n: noInstrument }));
    if (badQuantity) missing.push(t(badQuantity === 1 ? 'portfolio.importImage.pendingBadQuantityOne' : 'portfolio.importImage.pendingBadQuantityMany', { n: badQuantity }));
    if (unchecked) missing.push(t(unchecked === 1 ? 'portfolio.importImage.pendingUncheckedOne' : 'portfolio.importImage.pendingUncheckedMany', { n: unchecked }));
    return missing.length ? t('portfolio.importImage.pendingMissing', { items: missing.join(', ') }) : null;
}
