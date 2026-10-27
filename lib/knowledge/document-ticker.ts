/**
 * Biblioteca de conocimiento enlazada a un ticker (conexión 10a).
 *
 * Funciones puras, sin dependencias: las usan la server action de la
 * biblioteca y la ficha /research/[ticker]. El backend vuelve a normalizar y
 * valida la forma del ticker (400 si no la tiene); aquí solo se limpia.
 */

/** Valor del campo «ticker» de un formulario: strip + mayúsculas; vacío → null (quita el ticker). */
export function knowledgeTickerFormValue(value: FormDataEntryValue | null): string | null {
  if (typeof value !== 'string') return null;
  const normalized = value.trim().toUpperCase();
  return normalized === '' ? null : normalized;
}

/** Documentos listos de la biblioteca asociados a un ticker (máximo 50). */
export function libraryReadingsPath(ticker: string): string {
  return `/api/knowledge/documents?ticker=${encodeURIComponent(ticker)}&status=ready&limit=50`;
}

/** Enlace al explorador de fragmentos del documento en /knowledge. */
export function libraryDocumentHref(documentId: number): string {
  return `/knowledge?document=${documentId}`;
}
