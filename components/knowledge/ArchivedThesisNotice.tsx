import { createTranslator, type TranslateFn } from '@/lib/i18n/translate';

const esT: TranslateFn = createTranslator('es');

/** Context around an immutable archive, never a rewrite of its contents. */
export function ArchivedThesisNotice({ documentType, t = esT }: { documentType: string; t?: TranslateFn }) {
  if (documentType !== 'own_thesis') return null;
  return (
    <aside className="mb-4 rounded-lg border border-amber-900/60 bg-amber-950/20 p-3 text-sm leading-6 text-amber-200" role="note">
      {t('knowledge.archivedNotice')}
    </aside>
  );
}
