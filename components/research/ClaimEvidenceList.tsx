import type { ResearchClaimEvidence } from '@/lib/actions/research.actions';
import type { Locale } from '@/lib/i18n/locale';
import type { TranslateFn } from '@/lib/i18n/translate';
import { naFor } from '@/lib/format';
import { etiquetaTierFuente } from '@/lib/labels';

const MAX_ITEMS = 5;

/**
 * F249: source_url se persiste tal cual en varios caminos de ingesta, así que
 * no basta con que sea truthy: solo se enlaza una URL absoluta http(s) con
 * hostname. Cualquier otra cosa (javascript:, data:, relativa, malformada) se
 * queda como texto plano.
 */
export function safeHttpUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    if ((url.protocol === 'https:' || url.protocol === 'http:') && url.hostname) {
      return url.toString();
    }
  } catch {
    // malformada: texto plano
  }
  return null;
}

/**
 * Cadena Fuente→Documento→Chunk→Afirmación: expone los campos de evidencia
 * que el backend ya devuelve y la ficha descartaba. Sin URL http válida no se
 * inventa enlace: cae al documento_id persistido (o N/D según locale).
 */
export function ClaimEvidenceList({
  evidence,
  locale,
  t,
}: {
  evidence: ResearchClaimEvidence[];
  locale: Locale;
  t: TranslateFn;
}) {
  if (!evidence.length) return null;
  return (
    <details className="mt-3 rounded-lg border border-gray-800 p-3">
      <summary className="cursor-pointer text-xs font-semibold uppercase text-gray-500">
        {t('research.fichaEvidenceCount', { count: evidence.length })}
      </summary>
      <ul className="mt-2 space-y-2 text-xs text-gray-400">
        {evidence.slice(0, MAX_ITEMS).map((item) => {
          const safeUrl = safeHttpUrl(item.source_url);
          return (
            <li className="min-w-0 break-all" key={item.id}>
              <span className="font-medium text-gray-300">{etiquetaTierFuente(item.source_tier, locale)}</span>
              {' · '}
              <span>{t('common.labels.confidence')}: {item.confidence}</span>
              {' · '}
              {safeUrl ? (
                <a className="text-teal-300 underline decoration-gray-700 underline-offset-4 hover:text-teal-200" href={safeUrl} rel="noopener noreferrer" target="_blank">{safeUrl}</a>
              ) : (
                <span>{item.document_id !== null ? `#${item.document_id}` : naFor(locale)}</span>
              )}
            </li>
          );
        })}
      </ul>
      {evidence.length > MAX_ITEMS ? (
        <p className="mt-2 text-xs text-gray-500">
          {t('research.auditDetail.moreItems', { count: evidence.length - MAX_ITEMS })}
        </p>
      ) : null}
    </details>
  );
}
