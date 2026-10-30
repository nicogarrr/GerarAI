export type ImageRow = { raw: string; identity: string; quantity: string | null; currency: string | null; warning: string };
export type ConfirmedImageRow = { ticker: string; quantity: string; currency: string; confirmed: boolean };
export type ImagePreview = { image_hash: string; rows: ImageRow[]; message: string };
export type ImageInstrument = { ticker: string; name: string; exchange: string; currency: string };
export type ImageReview = { review_id: number; can_confirm: boolean; base_currency: string; already_imported: boolean; rows: Array<ConfirmedImageRow & { name: string; exchange: string; price: string | null; timestamp: number | null; source: string; value_native: string | null; value_base: string | null; weight_percent: string | null }> };

export function imageFileError(file: Pick<File, 'size' | 'type'>): string | null {
    if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) return 'Usa una imagen PNG, JPEG o WebP';
    if (file.size === 0 || file.size > 2 * 1024 * 1024) return 'La imagen debe ocupar como máximo 2 MB';
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
export function imageRowsPending(rows: Array<{ instrument: unknown; checked: boolean; quantity: string }>): string | null {
    if (rows.length === 0) return 'Añade al menos una fila.';
    const missing: string[] = [];
    const noInstrument = rows.filter(row => !row.instrument).length;
    const badQuantity = rows.filter(row => normalizeImageQuantity(row.quantity) === null).length;
    const unchecked = rows.filter(row => row.instrument && !row.checked).length;
    const n = (count: number, one: string, many: string) => `${count} ${count === 1 ? one : many}`;
    if (noInstrument) missing.push(n(noInstrument, 'fila sin instrumento elegido', 'filas sin instrumento elegido'));
    if (badQuantity) missing.push(n(badQuantity, 'cantidad no válida', 'cantidades no válidas'));
    if (unchecked) missing.push(n(unchecked, 'fila sin marcar como revisada', 'filas sin marcar como revisadas'));
    return missing.length ? `Falta: ${missing.join(', ')}.` : null;
}
