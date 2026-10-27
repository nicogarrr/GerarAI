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
