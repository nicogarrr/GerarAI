import type { ComponentProps } from 'react';

import { MutationForm } from '@/components/forms/MutationForm';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';

/**
 * Alta de una afirmación de la tesis (vista «tesis» de la ficha). Cada campo
 * lleva nombre accesible: el número de materialidad no tenía etiqueta y axe lo
 * marcaba como crítico (label); el lector de pantalla solo decía «0 a 10».
 */
export function ResearchClaimForm({ action }: { action: ComponentProps<typeof MutationForm>['action'] }) {
  return (
    <MutationForm action={action} className="mb-5 grid gap-3 sm:grid-cols-[1fr_150px_auto] sm:items-start" resetOnSuccess successMessage="Afirmación creada">
      <Textarea id="statement" name="statement" aria-label="Afirmación" placeholder="Una afirmación falsable y específica de la empresa" required className="min-h-[44px] text-base sm:text-sm" />
      <Input name="materiality_score" aria-label="Materialidad (0 a 10)" title="Materialidad (0 a 10)" type="number" min="0" max="10" defaultValue="5" className="h-11 text-base sm:h-9 sm:text-sm" />
      <Button type="submit" className="min-h-[44px] sm:min-h-0">Añadir afirmación</Button>
    </MutationForm>
  );
}
