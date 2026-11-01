'use client';

import { useFormStatus } from 'react-dom';
import { Loader2, Play } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { useT } from '@/lib/i18n/client';

/**
 * Botón de submit para el form ad-hoc de screeners (GET server-side):
 * muestra spinner y se deshabilita durante la navegación, para que el
 * envío nunca parezca silencioso.
 */
export function SubmitButton() {
  const { pending } = useFormStatus();
  const t = useT();
  return (
    <Button aria-disabled={pending} disabled={pending} type="submit">
      {pending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
      {pending ? t('screener.screens.running') : t('screener.screens.run')}
    </Button>
  );
}
