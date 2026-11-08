/** Etiquetas de los tipos de aviso (push y correo): una sola copia para
 *  PushNotifications y EmailNotifications, que la tenían duplicada y podían
 *  desviarse al dar de alta un tipo nuevo. */
import type { TranslationKey } from '@/lib/i18n/t';

import type { PushEventType } from './push-event-types';

export const PUSH_TYPE_LABEL_KEYS: Record<PushEventType, TranslationKey> = {
    macro_event: 'alerts.push.types.macroEvent',
    earnings: 'alerts.push.types.earnings',
    dca_levels: 'alerts.push.types.dcaLevels',
    new_filing: 'alerts.push.types.newFiling',
    thesis_broken: 'alerts.push.types.thesisBroken',
    insiders: 'alerts.push.types.insiders',
    shorts_rising: 'alerts.push.types.shortsRising',
    daily_digest: 'alerts.push.types.dailyDigest',
};
