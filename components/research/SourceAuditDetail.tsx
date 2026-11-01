import Link from 'next/link';
import { auditFixLabel } from '@/lib/audit-status-copy';
import { formatGeneratedDate } from '@/lib/format';
import type { Locale } from '@/lib/i18n/locale';
import { createTranslator, type TranslateFn } from '@/lib/i18n/translate';
import type { ResearchSourceAudit } from '@/lib/actions/research.actions';

const MAX_ITEMS = 5;

const RECONCILIATION_CLAIM_RE = /^SEC\/FMP reconciliation missing for reported financial facts\.?$/i;

const WEAK_CLAIM_ES: ReadonlyArray<[RegExp, string]> = [
  [RECONCILIATION_CLAIM_RE, 'Falta conciliar con SEC/FMP las cifras financieras reportadas.'],
];

export function weakClaimEs(text: string): string {
  for (const [pattern, es] of WEAK_CLAIM_ES) if (pattern.test(text.trim())) return es;
  return text;
}

/** Igual que weakClaimEs, pero con el texto del idioma elegido. */
function weakClaimLabel(text: string, t: TranslateFn): string {
  return RECONCILIATION_CLAIM_RE.test(text.trim()) ? t('research.auditDetail.reconciliationMissing') : text;
}

function ClaimList({ title, items, t }: { title: string; items: string[]; t: TranslateFn }) {
  if (!items.length) return null;
  return (
    <div className="mt-3">
      <div className="text-xs font-semibold uppercase text-gray-500">{title} ({items.length})</div>
      <ul className="mt-1 space-y-1 text-sm text-gray-300">
        {items.slice(0, MAX_ITEMS).map((item) => <li key={item}>{item}</li>)}
      </ul>
      {items.length > MAX_ITEMS ? <p className="mt-1 text-xs text-gray-500">{t('research.auditDetail.moreItems', { count: items.length - MAX_ITEMS })}</p> : null}
    </div>
  );
}

export function SourceAuditDetail({ audit, ticker, locale = 'es' }: { audit: ResearchSourceAudit; ticker: string; locale?: Locale }) {
  const t = createTranslator(locale);
  const date = formatGeneratedDate(audit.created_at, undefined, locale);
  const hasReason = audit.required_fixes.length + audit.unsupported_claims.length + audit.data_conflicts.length > 0;
  const onlyWeak = !audit.passed && !hasReason && audit.weak_claims.length > 0;
  return (
    <>
      <p className="mt-3 text-xs text-gray-500">
        {date ? `${date} · ` : ''}
        <Link className="text-teal-300 hover:text-teal-200" href={`/research/${encodeURIComponent(ticker)}?view=thesis`}>
          {t('research.auditDetail.viewThesis')}{audit.thesis_version != null ? ` v${audit.thesis_version}` : ''}
        </Link>
      </p>
      {audit.required_fixes.length ? <p className="mt-3 text-sm text-amber-300">{audit.required_fixes.map((fix) => auditFixLabel(fix, locale)).join(' · ')}</p> : null}
      {onlyWeak ? <p className="mt-3 text-sm text-amber-300">{t('research.auditDetail.blockedWeakOnly')}</p> : null}
      {!audit.passed && !hasReason && !onlyWeak ? <p className="mt-3 text-sm text-amber-300">{t('research.auditDetail.blockedNoReason')}</p> : null}
      <ClaimList t={t} title={t('research.auditDetail.unsupportedClaims')} items={audit.unsupported_claims} />
      <ClaimList t={t} title={t('research.auditDetail.dataConflicts')} items={audit.data_conflicts} />
      {/* La conciliación ausente NO es una afirmación de baja confianza, aunque
          el backend la devuelva en weak_claims: con su propio título el -5 de la
          puntuación se puede explicar con lo que se muestra. */}
      <ClaimList t={t} title={t('research.auditDetail.lowConfidence')} items={audit.weak_claims.filter((claim) => !RECONCILIATION_CLAIM_RE.test(claim.trim())).map((claim) => weakClaimLabel(claim, t))} />
      <ClaimList t={t} title={t('research.auditDetail.reconciliation')} items={audit.weak_claims.filter((claim) => RECONCILIATION_CLAIM_RE.test(claim.trim())).map((claim) => weakClaimLabel(claim, t))} />
    </>
  );
}
