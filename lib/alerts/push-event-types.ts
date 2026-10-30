/** Tipos de avisos Web Push compartidos; no es un módulo de server actions. */
export const PUSH_EVENT_TYPES = [
    'thesis_broken',
    'new_filing',
    'insiders',
    'shorts_rising',
    'daily_digest',
    'dca_levels',
    'macro_event',
    'earnings',
] as const;

export type PushEventType = (typeof PUSH_EVENT_TYPES)[number];

