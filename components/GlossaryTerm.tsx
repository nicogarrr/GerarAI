'use client';

import { HelpCircle } from 'lucide-react';

import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { glossaryFor, moatGlossaryKey, moatLabel, type GlossaryKey } from '@/lib/glossary';
import { useLocale } from '@/lib/i18n/client';

interface GlossaryTermProps {
  /** Clave del glosario (ver lib/glossary.ts). */
  k: GlossaryKey;
  /** Texto visible; por defecto, el término del glosario. */
  children?: React.ReactNode;
  /** Muestra el icono de ayuda junto al texto (por defecto sí). */
  icon?: boolean;
}

/**
 * Término con tooltip didáctico: subrayado punteado + definición al pasar
 * el ratón o enfocar con teclado. Aceptado por componentes server.
 */
export function GlossaryTerm({ k, children, icon = true }: GlossaryTermProps) {
  const entry = glossaryFor(useLocale())[k];
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          tabIndex={0}
          className="cursor-help underline decoration-dotted decoration-gray-500 underline-offset-4"
        >
          {children ?? entry.term}
          {icon ? <HelpCircle className="ml-1 inline h-3 w-3 align-baseline text-gray-500" /> : null}
        </span>
      </TooltipTrigger>
      <TooltipContent>
        <p className="font-semibold text-gray-100">{entry.term}</p>
        <p className="mt-1 text-gray-300">{entry.short}</p>
      </TooltipContent>
    </Tooltip>
  );
}

interface MoatTermProps {
  /** Clave de moat del backend (p. ej. `network_effects`). */
  type: string;
}

/**
 * Etiqueta de moat en español con su definición en tooltip. Si el backend
 * manda una clave desconocida, muestra el texto sin tooltip (sin inventar).
 */
export function MoatTerm({ type }: MoatTermProps) {
  const locale = useLocale();
  const key = moatGlossaryKey[type];
  if (!key) return <span className="font-medium text-gray-200">{moatLabel(type, locale)}</span>;
  return (
    <GlossaryTerm k={key} icon={false}>
      <span className="font-medium text-gray-200">{moatLabel(type, locale)}</span>
    </GlossaryTerm>
  );
}
