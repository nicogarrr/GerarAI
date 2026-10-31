import { ExternalLink } from 'lucide-react';
import { t, type TranslationKey, type TranslationVars } from '@/lib/i18n/t';
import type { MacroEvent } from '@/lib/actions/macro-calendar.actions';

type TiFn = (key: TranslationKey, vars?: TranslationVars) => string;
/** Fallback español sin RequestScope (tests y render directo): el acceso es de main (lib/i18n/t). */
const esT: TiFn = t;

/** Badge de calidad del dato (OFICIAL): se conserva; no es una etiqueta de fuente. */
export function SourceBadge({ children }: { children: React.ReactNode }) {
    return <span className="rounded border border-teal-400/30 px-1.5 py-0.5 text-[11px] font-semibold uppercase text-teal-300">{children}</span>;
}

/** Fila de evento macro. El enlace del documento lleva icono y aria genérico:
    el nombre de la fuente queda en la API y no se pinta (patrón de #3527). */
export function MacroEventRow({ event, dateLabel, ti = esT }: { event: MacroEvent; dateLabel: string; ti?: TiFn }) {
    return (
        <li className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3">
            <span className="w-28 text-sm font-medium text-gray-100">{dateLabel}</span>
            <span className="flex-1 text-sm text-gray-200">
                {event.title}
                {event.detail ? <span className="text-gray-500"> · {event.detail}</span> : null}
            </span>
            {event.time_et && <span className="text-xs text-gray-500">{event.time_et} ET</span>}
            <SourceBadge>{ti('calendar.macro.official')}</SourceBadge>
            <a
                className="inline-flex h-11 w-11 items-center justify-center rounded-lg text-gray-500 hover:bg-gray-800 hover:text-gray-200 sm:h-9 sm:w-9"
                href={event.source_url}
                target="_blank"
                rel="noopener noreferrer"
                aria-label={ti('calendar.macro.docAria')}
            >
                <ExternalLink aria-hidden="true" className="h-4 w-4" />
            </a>
        </li>
    );
}
