import type { ComponentProps } from 'react';

import { MutationForm } from '@/components/forms/MutationForm';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import type { Locale } from '@/lib/i18n/locale';
import { createTranslator } from '@/lib/i18n/translate';

/**
 * Alta de una afirmación de la tesis (vista «tesis» de la ficha). Cada campo
 * lleva nombre accesible: el número de materialidad no tenía etiqueta y axe lo
 * marcaba como crítico (label); el lector de pantalla solo decía «0 a 10».
 */
export function ResearchClaimForm({ action, locale = 'es' }: { action: ComponentProps<typeof MutationForm>['action']; locale?: Locale }) {
  const t = createTranslator(locale);
  return (
    <MutationForm action={action} className="mb-5 grid gap-3 sm:grid-cols-[1fr_150px_auto] sm:items-start" resetOnSuccess successMessage={t('research.claimForm.created')}>
      <Textarea id="statement" name="statement" aria-label={t('research.claimForm.statementLabel')} placeholder={t('research.claimForm.statementPlaceholder')} required className="min-h-[44px] text-base sm:text-sm" />
      <Input name="materiality_score" aria-label={t('research.claimForm.materiality')} title={t('research.claimForm.materiality')} type="number" min="0" max="10" defaultValue="5" className="h-11 text-base sm:h-9 sm:text-sm" />
      <Button type="submit" className="min-h-[44px] sm:min-h-0">{t('research.claimForm.submit')}</Button>
    </MutationForm>
  );
}
