/** Descarga un Blob como archivo: enlace temporal + click + revocación.
 *  Cinco vistas copiaban este flujo; la tarjeta del vault Obsidian revoca
 *  diferido a propósito (Safari/iOS) y no usa este helper. */
export function downloadBlob(filename: string, blob: Blob): void {
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
}
